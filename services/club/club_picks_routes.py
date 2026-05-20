"""
Club Picks Routes - API endpoints for managing club picks/bets
"""

from fastapi import APIRouter, HTTPException, status, Depends, Query, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import Optional
import logging
import math

from .models import (
    ClubPickCreateRequest,
    ClubPickUpdateRequest,
    ClubPickResponse,
    ClubPickListResponse,
    ClubPickStatsResponse,
    ClubLeaderboardResponse,
    GlobalLeaderboardResponse,
    ClubwiseLeaderboardResponse,
    PickStatus,BetSource,
    PickEntityType
)
from .club_picks_service import get_club_picks_service
from .auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/club-picks", tags=["Club Picks"])


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


@router.post("/")
async def create_pick(
    pick_data: ClubPickCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new pick/bet for a club.
    
    Only captains and moderators of the club can submit picks.
    
    **Requirements:**
    - User must be authenticated
    - User must be either the captain or a moderator of the club
    - If status is 'completed', result must be provided
    
    **Fields:**
    - `club_id`: Club name-based ID (required)
    - `bet_source`: Source of the bet - "live-support" or "manual-entry" (required)
    - `sport`: Sport name (e.g., "Basketball", "Football") (required)
    - `league`: League name (e.g., "NBA", "NFL") (required)
    - `pick_entity_type`: "team" or "player" (required)
    - `team1`: First team name (required if pick_entity_type is "team")
    - `team2`: Second team name (required if pick_entity_type is "team")
    - `player_name`: Player name (required if pick_entity_type is "player")
    - `bet_on_team`: Which team the bet is on (required if bet_source is "manual-entry" and pick_entity_type is "team")
    - `match_datetime`: Date and time when the match/game will happen (ISO 8601 format) (required)
    - `platform`: Betting platform (e.g., "DraftKings", "FanDuel") (required)
    - `pick_type`: Type of pick - accepts any custom value including "Parlay" (required)
    - `status`: Status - "pending" or "completed" (default: "pending")
    - `reasoning`: Optional reasoning for the pick
    - `result`: Result - "win" or "loss" (required if status is "completed")
    - `bet_logo`: Optional URL of the bet logo/image
    - `parlay_picks`: Array of parlay picks (required when pick_type is "Parlay", must have 2-10 picks)
    
    **Validation Rules:**
    
    1. **Live Support Bet (team, non-parlay):**
       - Only "Basketball" or "American Football" are allowed for sport
       - `bet_on_team` should NOT be included
    
    2. **Live Support Bet (player, non-parlay):**
       - Only "Basketball" or "American Football" are allowed for sport
       - `bet_on_team` should NOT be included
    
    3. **Manual Entry Bet (team, non-parlay):**
       - Any sport allowed
       - `bet_on_team` is REQUIRED
    
    4. **Manual Entry Bet (player, non-parlay):**
       - Any sport allowed
       - `bet_on_team` should NOT be included
    
    5. **Parlay Bet (any bet_source, any pick_entity_type):**
       - `parlay_picks` array is REQUIRED (2-10 picks)
       - Each parlay pick must have: market_type, sport, league, pick_entity_type, bet_for, match_datetime
       - If pick_entity_type is "team": team1 and team2 are required
       - If pick_entity_type is "player": player_name is required
    
    **Note:** Status and result fields are case-insensitive. Pick type accepts any custom string value.
    """
    try:
        service = get_club_picks_service()
        
        # Convert parlay_picks to dict format if provided
        # Set parlay_status="pending" by default for each parlay pick
        parlay_picks_dict = None
        if pick_data.parlay_picks:
            parlay_picks_dict = []
            for pick in pick_data.parlay_picks:
                pick_dict = pick.model_dump()
                # Ensure parlay_status is set to "pending" by default if not provided
                if "parlay_status" not in pick_dict or not pick_dict["parlay_status"]:
                    pick_dict["parlay_status"] = "pending"
                # Ensure parlay_status is lowercase
                if pick_dict.get("parlay_status"):
                    pick_dict["parlay_status"] = pick_dict["parlay_status"].lower()
                # Ensure parlay_result is lowercase if provided
                if pick_dict.get("parlay_result"):
                    pick_dict["parlay_result"] = pick_dict["parlay_result"].lower()
                parlay_picks_dict.append(pick_dict)
        
        pick = await service.create_pick(
            user_id=current_user["user_id"],
            club_id=pick_data.club_id,
            bet_source=pick_data.bet_source.value if pick_data.bet_source else None,
            sport=pick_data.sport,
            league=pick_data.league,
            pick_entity_type=pick_data.pick_entity_type.value if pick_data.pick_entity_type else None,
            team1=pick_data.team1,
            team2=pick_data.team2,
            player_name=pick_data.player_name,
            bet_on_team=pick_data.bet_on_team,
            player_id=pick_data.player_id,
            home_team_id=pick_data.home_team_id,
            away_team_id=pick_data.away_team_id,
            bet_on_team_id=pick_data.bet_on_team_id,
            league_id=pick_data.league_id,
            match_id=pick_data.match_id,
            match_datetime=pick_data.match_datetime,
            platform=pick_data.platform,
            pick_type=pick_data.pick_type,
            status=pick_data.status.value,
            reasoning=pick_data.reasoning,
            result=pick_data.result.value if pick_data.result else None,
            bet_logo=pick_data.bet_logo,
            parlay_picks=parlay_picks_dict,
            home_logo=pick_data.home_logo,
            away_logo=pick_data.away_logo
        )
        
        # Helper function to format datetime
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, str):
                return dt
            return dt.isoformat() + "Z" if dt.tzinfo else dt.isoformat() + "+00:00"
        
        pick_response = {
            "id": pick["_id"],
            "club_id": pick["club_id"],
            "club_name": pick.get("club_name"),
            "submitted_by": pick.get("submitted_by_name", pick.get("submitted_by")),
            "submitted_by_id": pick.get("submitted_by_id", pick.get("submitted_by")),
            "submitted_by_role": pick["submitted_by_role"],
            "bet_source": pick.get("bet_source"),
            "sport": pick["sport"],
            "league": pick["league"],
            "pick_entity_type": pick["pick_entity_type"],
            "team1": pick.get("team1"),
            "team2": pick.get("team2"),
            "player_name": pick.get("player_name"),
            "bet_on_team": pick.get("bet_on_team"),
            "player_id": pick.get("player_id"),
            "home_team_id": pick.get("home_team_id"),
            "away_team_id": pick.get("away_team_id"),
            "bet_on_team_id": pick.get("bet_on_team_id"),
            "league_id": pick.get("league_id"),
            "match_id": pick.get("match_id"),
            "match_datetime": format_datetime(pick["match_datetime"]),
            "platform": pick["platform"],
            "pick_type": pick["pick_type"],
            "status": pick["status"],
            "reasoning": pick.get("reasoning"),
            "result": pick.get("result"),
            "bet_logo": pick.get("bet_logo"),
            "parlay_picks": pick.get("parlay_picks"),
            "created_at": format_datetime(pick["created_at"]),
            "updated_at": format_datetime(pick["updated_at"])
        }
        
        return create_response(
            status_code=201,
            status="success",
            message="Pick created successfully",
            data=pick_response
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error creating pick: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error creating pick: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to create pick: {str(e)}",
            data=None
        )


@router.get("/club/{club_id}")
async def get_club_picks(
    club_id: str,
    status_filter: Optional[PickStatus] = Query(None, description="Filter by status (accepts: Pending, pending, Completed, completed)"),
    pick_type_filter: Optional[str] = Query(None, description="Filter by pick type (moneyline, parlay, spread, etc.)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    bet_source_filter: Optional[BetSource] = Query(None, description="Filter by bet source (accepts: live-support, manual-entry)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get all picks for a specific club.
    
    **Query Parameters:**
    - `status_filter`: Optional filter by status (accepts: Pending, pending, Completed, completed)
    - `pick_type_filter`: Optional filter by pick type (moneyline, parlay, spread, etc.)
    - `page`: Page number (default: 1)
    - `limit`: Items per page (default: 20, max: 100)
    
    **Returns:**
    - List of picks with pagination information
    - Status and result values are returned in lowercase (pending/completed, win/loss)
    """
    try:
        service = get_club_picks_service()
        
        skip = (page - 1) * limit
        
        result = await service.get_picks_by_club(
            club_id=club_id,
            status_filter=status_filter.value if status_filter else None,
            pick_type_filter=pick_type_filter,
            bet_source_filter=bet_source_filter.value if bet_source_filter else None,
            limit=limit,
            skip=skip
        )
        
        picks = [
            {
                "id": pick["_id"],
                "club_id": pick["club_id"],
                "club_name": pick.get("club_name"),
                "submitted_by": pick.get("submitted_by_name", pick.get("submitted_by")),
                "submitted_by_id": pick.get("submitted_by_id", pick.get("submitted_by")),
                "submitted_by_role": pick["submitted_by_role"],
                "sport": pick["sport"],
                "league": pick["league"],
                "pick_entity_type": pick["pick_entity_type"],
                "team1": pick.get("team1"),
                "team2": pick.get("team2"),
                "player_name": pick.get("player_name"),
                "bet_on_team": pick.get("bet_on_team"),
                "player_id": pick.get("player_id"),
                "home_team_id": pick.get("home_team_id"),
                "away_team_id": pick.get("away_team_id"),
                "bet_on_team_id": pick.get("bet_on_team_id"),
                "league_id": pick.get("league_id"),
                "match_id": pick.get("match_id"),
                "match_datetime": pick["match_datetime"],
                "platform": pick["platform"],
                "pick_type": pick["pick_type"],
                "status": pick["status"],
                "reasoning": pick.get("reasoning"),
                "result": pick.get("result"),
                "created_at": pick["created_at"],
                "updated_at": pick["updated_at"],
                "bet_logo": pick.get("bet_logo"),
                "bet_source":pick.get("bet_source"),
            }
            for pick in result["picks"]
        ]
        
        total_pages = math.ceil(result["total"] / limit) if limit > 0 else 0
        
        response_data = {
            "picks": picks,
            "total": result["total"],
            "limit": limit,
            "skip": skip,
            "page": page,
            "total_pages": total_pages
        }
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Retrieved {len(picks)} pick(s) for club {club_id}",
            data=response_data
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error getting club picks: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error getting club picks: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to get club picks: {str(e)}",
            data=None
        )


@router.get("/{pick_id}")
async def get_pick_by_id(
    pick_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a specific pick by ID.
    
    **Parameters:**
    - `pick_id`: Pick ID
    
    **Returns:**
    - Pick details
    """
    try:
        service = get_club_picks_service()
        pick = await service.get_pick_by_id(pick_id)
        
        pick_response = {
            "id": pick["_id"],
            "club_id": pick["club_id"],
            "club_name": pick.get("club_name"),
            "submitted_by": pick.get("submitted_by_name", pick.get("submitted_by")),
            "submitted_by_id": pick.get("submitted_by_id", pick.get("submitted_by")),
            "submitted_by_role": pick["submitted_by_role"],
            "sport": pick["sport"],
            "league": pick["league"],
            "pick_entity_type": pick["pick_entity_type"],
            "team1": pick.get("team1"),
            "team2": pick.get("team2"),
            "player_name": pick.get("player_name"),
            "bet_on_team": pick.get("bet_on_team"),
            "player_id": pick.get("player_id"),
            "home_team_id": pick.get("home_team_id"),
            "away_team_id": pick.get("away_team_id"),
            "bet_on_team_id": pick.get("bet_on_team_id"),
            "league_id": pick.get("league_id"),
            "match_id": pick.get("match_id"),
            "match_datetime": pick["match_datetime"],
            "platform": pick["platform"],
            "pick_type": pick["pick_type"],
            "status": pick["status"],
            "reasoning": pick.get("reasoning"),
            "result": pick.get("result"),
            "bet_logo": pick.get("bet_logo"),
            "created_at": pick["created_at"],
            "updated_at": pick["updated_at"]
        }
        
        return create_response(
            status_code=200,
            status="success",
            message="Pick retrieved successfully",
            data=pick_response
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error getting pick: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error getting pick: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to get pick: {str(e)}",
            data=None
        )


@router.put("/{pick_id}")
async def update_pick(
    pick_id: str,
    update_data: ClubPickUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Update a pick.
    
    Only captains and moderators of the club can update picks.
    
    **Parameters:**
    - `pick_id`: Pick ID to update
    
    **Request Body:**
    - Any fields from ClubPickUpdateRequest that need to be updated
    - `pick_type`: Type of pick - accepts ANY custom value (e.g., 'Over/under', 'Moneyline', 'Overlay', or any other custom type)
    - `status`: Accepts Pending/pending, Completed/completed (case-insensitive, stored as lowercase)
    - `result`: Accepts Win/win, Loss/loss (case-insensitive, stored as lowercase)
    
    **Returns:**
    - Updated pick details with status and result in lowercase
    
    **Note:** Status and result fields are case-insensitive. Pick type accepts any custom string value.
    """
    try:
        service = get_club_picks_service()
        
        # Convert Pydantic model to dict, excluding None values
        update_dict = update_data.model_dump(exclude_none=True)
        
        # Convert enum values to strings
        if "pick_entity_type" in update_dict:
            update_dict["pick_entity_type"] = update_dict["pick_entity_type"].value
        # pick_type is already a string, no conversion needed
        if "status" in update_dict:
            update_dict["status"] = update_dict["status"].value
        if "result" in update_dict:
            update_dict["result"] = update_dict["result"].value
        
        # Handle parlay_picks if provided (for editing parlay picks)
        # parlay_picks is already a list of dicts from the model, so we can process it directly
        if "parlay_picks" in update_dict and update_dict["parlay_picks"]:
            parlay_picks_list = []
            for pick in update_dict["parlay_picks"]:
                # pick is already a dict since we changed the model
                pick_dict = pick.copy() if isinstance(pick, dict) else pick
                
                # Ensure parlay_status is set to "pending" by default if not provided
                if "parlay_status" not in pick_dict or not pick_dict.get("parlay_status"):
                    pick_dict["parlay_status"] = "pending"
                
                # Ensure parlay_status is lowercase
                if pick_dict.get("parlay_status"):
                    pick_dict["parlay_status"] = pick_dict["parlay_status"].lower()
                
                # Ensure parlay_result is lowercase if provided
                if pick_dict.get("parlay_result"):
                    pick_dict["parlay_result"] = pick_dict["parlay_result"].lower()
                
                parlay_picks_list.append(pick_dict)
            
            update_dict["parlay_picks"] = parlay_picks_list
        
        pick = await service.update_pick(
            pick_id=pick_id,
            user_id=current_user["user_id"],
            update_data=update_dict
        )
        
        pick_response = {
            "id": pick["_id"],
            "club_id": pick["club_id"],
            "club_name": pick.get("club_name"),
            "submitted_by": pick.get("submitted_by_name", pick.get("submitted_by")),
            "submitted_by_id": pick.get("submitted_by_id", pick.get("submitted_by")),
            "submitted_by_role": pick["submitted_by_role"],
            "sport": pick["sport"],
            "league": pick["league"],
            "pick_entity_type": pick["pick_entity_type"],
            "team1": pick.get("team1"),
            "team2": pick.get("team2"),
            "player_name": pick.get("player_name"),
            "bet_on_team": pick.get("bet_on_team"),
            "player_id": pick.get("player_id"),
            "home_team_id": pick.get("home_team_id"),
            "away_team_id": pick.get("away_team_id"),
            "bet_on_team_id": pick.get("bet_on_team_id"),
            "league_id": pick.get("league_id"),
            "match_id": pick.get("match_id"),
            "match_datetime": pick["match_datetime"],
            "platform": pick["platform"],
            "pick_type": pick["pick_type"],
            "status": pick["status"],
            "reasoning": pick.get("reasoning"),
            "result": pick.get("result"),
            "bet_logo": pick.get("bet_logo"),
            "parlay_picks": pick.get("parlay_picks"),
            "created_at": pick["created_at"],
            "updated_at": pick["updated_at"]
        }
        
        return create_response(
            status_code=200,
            status="success",
            message="Pick updated successfully",
            data=pick_response
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error updating pick: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error updating pick: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to update pick: {str(e)}",
            data=None
        )


@router.delete("/{pick_id}")
async def delete_pick(
    pick_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a pick (soft delete).
    
    Only captains and moderators of the club can delete picks.
    
    **Parameters:**
    - `pick_id`: Pick ID to delete
    
    **Returns:**
    - Success message
    """
    try:
        service = get_club_picks_service()
        
        success = await service.delete_pick(
            pick_id=pick_id,
            user_id=current_user["user_id"]
        )
        
        if not success:
            return create_response(
                status_code=500,
                status="error",
                message="Failed to delete pick",
                data=None
            )
        
        return create_response(
            status_code=200,
            status="success",
            message="Pick deleted successfully",
            data={"pick_id": pick_id}
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error deleting pick: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error deleting pick: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to delete pick: {str(e)}",
            data=None
        )


@router.get("/club/{club_id}/statistics")
async def get_club_pick_statistics(
    club_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get statistics for club picks.
    
    **Parameters:**
    - `club_id`: Club name-based ID
    
    **Returns:**
    - Statistics including total picks, wins, losses, and win percentage
    """
    try:
        service = get_club_picks_service()
        stats = await service.get_club_picks_statistics(club_id)
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Statistics retrieved for club {club_id}",
            data=stats
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error getting pick statistics: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error getting pick statistics: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to get pick statistics: {str(e)}",
            data=None
        )


@router.get("/club/{club_id}/leaderboard")
async def get_club_leaderboard(
    club_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get leaderboard for a specific club.
    
    Shows performance statistics for all captains and moderators in the club,
    ranked by win percentage and total wins.
    
    **Authorization:**
    - Captain of the club
    - Moderator of the club
    - Active member of the club
    
    **Parameters:**
    - `club_id`: Club name-based ID
    
    **Ranking Logic:**
    - Users are ranked by: win percentage (desc) → total wins (desc) → total picks (desc)
    - **Tie-breaking**: Users with identical stats (same total picks, win percentage, and wins) receive the same rank
    - **Dense Ranking**: If 3 users have 100 picks, 75% win rate, and 75 wins → all rank 1, next user is rank 2
    
    **Returns:**
    - Leaderboard with rankings, stats, and user details
    
    **Example Response:**
    ```json
    {
      "club_id": "elite-bettors",
      "club_name": "Elite Bettors Club",
      "total_participants": 4,
      "leaderboard": [
        {
          "rank": 1,
          "user_id": "user123",
          "full_name": "John Doe",
          "role": "captain",
          "total_picks": 100,
          "wins": 70,
          "losses": 30,
          "pending": 0,
          "win_percentage": 70.0,
          "avatar_url": "/uploads/avatars/user123.jpg"
        },
        {
          "rank": 2,
          "user_id": "user456",
          "full_name": "Jane Smith",
          "role": "moderator",
          "total_picks": 50,
          "wins": 30,
          "losses": 20,
          "pending": 0,
          "win_percentage": 60.0,
          "avatar_url": null
        }
      ]
    }
    ```
    
    **Note:**
    - Participants with no picks will show 0 for all stats
    - Sorted by win percentage (highest first), then by total wins
    - Only active moderators are included
    """
    try:
        service = get_club_picks_service()
        
        leaderboard = await service.get_club_leaderboard(
            club_id=club_id,
            user_id=current_user["user_id"]
        )
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Leaderboard retrieved for club {club_id}",
            data=leaderboard
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error getting leaderboard: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error getting leaderboard: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to get leaderboard: {str(e)}",
            data=None
        )


@router.get("/debug/clubs")
async def debug_clubs(
    current_user: dict = Depends(get_current_user)
):
    """
    Debug endpoint to check club status and structure
    """
    try:
        from .club_picks_service import get_club_picks_service
        service = get_club_picks_service()
        
        # Check total clubs
        total_clubs = await service.clubs_collection.count_documents({})
        
        # Check different status fields
        approved_clubs = await service.clubs_collection.count_documents({"status": "approved"})
        active_clubs = await service.clubs_collection.count_documents({"is_active": True})
        
        # Get first few clubs
        sample_clubs = await service.clubs_collection.find({}).limit(3).to_list(length=None)
        
        clubs_info = []
        for club in sample_clubs:
            clubs_info.append({
                "name": club.get("name"),
                "name_based_id": club.get("name_based_id"),
                "status": club.get("status"),
                "is_active": club.get("is_active"),
                "captain_id": club.get("captain_id"),
                "moderators_count": len(club.get("moderators", [])),
                "detailed_moderators_count": len(club.get("detailed_moderators", []))
            })
        
        return create_response(
            status_code=200,
            status="success",
            message="Debug info retrieved",
            data={
                "total_clubs": total_clubs,
                "approved_clubs": approved_clubs,
                "active_clubs": active_clubs,
                "sample_clubs": clubs_info
            }
        )
        
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Debug failed: {str(e)}",
            data=None
        )


@router.get("/debug/club/{club_id}/membership")
async def debug_club_membership(
    club_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Debug endpoint to check user's membership in a specific club
    """
    try:
        from .club_picks_service import get_club_picks_service
        from .my_clubs_service import MyClubsService
        
        service = get_club_picks_service()
        my_clubs_service = MyClubsService()
        
        user_id = current_user["user_id"]
        
        # Get club details
        club = await service.clubs_collection.find_one({"name_based_id": club_id})
        
        if not club:
            return create_response(
                status_code=404,
                status="error",
                message=f"Club '{club_id}' not found",
                data=None
            )
        
        # Get user role using the same method as leaderboard
        user_role = await my_clubs_service._determine_user_role_in_club(user_id, str(club["_id"]))
        
        # Get detailed membership info
        members = club.get("members", [])
        paid_members = club.get("paid_members", [])
        
        # Find user in members arrays
        user_member_info = None
        for member in members:
            if member.get("user_id") == user_id:
                user_member_info = member
                break
        
        if not user_member_info:
            for member in paid_members:
                if member.get("user_id") == user_id:
                    user_member_info = member
                    break
        
        return create_response(
            status_code=200,
            status="success",
            message="Membership debug info retrieved",
            data={
                "user_id": user_id,
                "club_id": club_id,
                "club_name": club.get("name"),
                "club_object_id": str(club["_id"]),
                "user_role": user_role,
                "captain_id": club.get("captain_id"),
                "total_trial_members": len(members),
                "total_paid_members": len(paid_members),
                "user_member_info": user_member_info,
                "trial_member_ids": [m.get("user_id") for m in members],
                "paid_member_ids": [m.get("user_id") for m in paid_members]
            }
        )
        
    except Exception as e:
        logger.error(f"Error in debug membership endpoint: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Debug failed: {str(e)}",
            data=None
        )


@router.get("/debug/club/{club_id}/raw-data")
async def debug_club_raw_data(
    club_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Debug endpoint to see raw club data
    """
    try:
        from .club_picks_service import get_club_picks_service
        
        service = get_club_picks_service()
        
        # Get club details
        club = await service.clubs_collection.find_one({"name_based_id": club_id})
        
        if not club:
            return create_response(
                status_code=404,
                status="error",
                message=f"Club '{club_id}' not found",
                data=None
            )
        
        # Return raw club data (excluding sensitive fields)
        safe_club_data = {
            "name": club.get("name"),
            "name_based_id": club.get("name_based_id"),
            "_id": str(club["_id"]),
            "captain_id": club.get("captain_id"),
            "status": club.get("status"),
            "is_active": club.get("is_active"),
            "members": club.get("members", []),
            "paid_members": club.get("paid_members", []),
            "moderators": club.get("moderators", []),
            "detailed_moderators": club.get("detailed_moderators", [])
        }
        
        return create_response(
            status_code=200,
            status="success",
            message="Raw club data retrieved",
            data=safe_club_data
        )
        
    except Exception as e:
        logger.error(f"Error in debug raw data endpoint: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Debug failed: {str(e)}",
            data=None
        )


@router.get("/leaderboard/global")
async def get_global_leaderboard(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str = Query(None, description="Search by club name or user full name"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get global leaderboard showing all captains and moderators from all clubs.
    
    Shows performance statistics for all active captains and moderators across
    all clubs, ranked by win percentage.
    
    **Authorization:**
    - Any authenticated user can access this endpoint
    
    **Query Parameters:**
    - `page`: Page number (default: 1)
    - `limit`: Items per page (default: 20, max: 100)
    - `search`: Optional search term to filter by club name or user full name
    
    **Ranking Logic:**
    - Users are ranked by: win percentage (desc) → total wins (desc) → total picks (desc)
    - **Tie-breaking**: Users with identical stats (same total picks, win percentage, and wins) receive the same rank
    - **Dense Ranking**: If 3 users have 100 picks, 75% win rate, and 75 wins → all rank 1, next user is rank 2
    
    **Returns:**
    - Global leaderboard with rankings from all clubs
    
    **Example Response:**
    ```json
    {
      "total_participants": 50,
      "page": 1,
      "limit": 20,
      "total_pages": 3,
      "leaderboard": [
        {
          "rank": 1,
          "user_id": "user123",
          "full_name": "John Doe",
          "user_role": "captain",
          "club_id": "elite-bettors",
          "club_name": "Elite Bettors",
          "total_picks": 100,
          "wins": 80,
          "losses": 20,
          "win_percentage": 80.0,
          "avatar_url": "/uploads/avatars/john.jpg"
        }
      ]
    }
    ```
    """
    try:
        service = get_club_picks_service()
        
        leaderboard = await service.get_global_leaderboard(
            page=page,
            limit=limit,
            search=search
        )
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Global leaderboard retrieved",
            data=leaderboard
        )
        
    except Exception as e:
        logger.error(f"Error getting global leaderboard: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to get global leaderboard: {str(e)}",
            data=None
        )


@router.get("/leaderboard/clubwise")
async def get_clubwise_leaderboard(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str = Query(None, description="Search by club name or user full name"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get clubwise leaderboard showing rankings from clubs the user is part of.
    
    Shows performance statistics for captains and moderators from clubs where
    the user is a captain, moderator, or member.
    
    **Authorization:**
    - Any authenticated user can access this endpoint
    
    **Query Parameters:**
    - `page`: Page number (default: 1)
    - `limit`: Items per page (default: 20, max: 100)
    - `search`: Optional search term to filter by club name or user full name
    
    **Ranking Logic:**
    - Users are ranked by: win percentage (desc) → total wins (desc) → total picks (desc)
    - **Tie-breaking**: Users with identical stats (same total picks, win percentage, and wins) receive the same rank
    - **Dense Ranking**: If 3 users have 100 picks, 75% win rate, and 75 wins → all rank 1, next user is rank 2
    
    **Returns:**
    - Clubwise leaderboard from user's clubs
    
    **Example Response:**
    ```json
    {
      "user_id": "user123",
      "total_clubs": 3,
      "page": 1,
      "limit": 20,
      "total_pages": 1,
      "leaderboard": [
        {
          "rank": 1,
          "club_id": "elite-bettors",
          "club_name": "Elite Bettors",
          "club_logo_url": "/uploads/logos/elite.jpg",
          "user_id": "user123",
          "full_name": "John Doe",
          "user_role": "captain",
          "total_picks": 100,
          "wins": 80,
          "losses": 20,
          "win_percentage": 80.0
        }
      ]
    }
    ```
    """
    try:
        service = get_club_picks_service()
        
        leaderboard = await service.get_clubwise_leaderboard(
            user_id=current_user["user_id"],
            page=page,
            limit=limit,
            search=search
        )
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Clubwise leaderboard retrieved",
            data=leaderboard
        )
        
    except Exception as e:
        logger.error(f"Error getting clubwise leaderboard: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to get clubwise leaderboard: {str(e)}",
            data=None
        )


@router.post("/upload-slip")
async def upload_betting_slip(
    club_id: str = Form(..., description="Club name-based ID"),
    pick_entity_type: str = Form(..., description="Whether pick is for 'team' or 'player'"),
    slip_image: UploadFile = File(..., description="Betting slip image"),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a betting slip image and extract pick details using AI.
    
    This endpoint uses OpenAI Vision API to analyze the betting slip image
    and automatically extract all relevant information.
    
    **Form Data:**
    - `club_id`: Club name-based ID (required)
    - `pick_entity_type`: Either "team" or "player" (required)
    - `slip_image`: Image file of the betting slip (required)
    
    **Returns:**
    - Extracted pick details in JSON format including:
      - sport, league, team1, team2 (or player_name)
      - match_datetime, platform, pick_type, status
      - reasoning (odds/details from slip)
      - slip_image_url (path to saved image)
    
    **Example Response:**
    ```json
    {
      "sport": "Football",
      "league": "NFL",
      "pick_entity_type": "team",
      "team1": "Kansas City Chiefs",
      "team2": "Las Vegas Raiders",
      "match_datetime": "2025-10-13T13:00:00Z",
      "platform": "BetMGM",
      "pick_type": "spread",
      "status": "pending",
      "reasoning": "Chiefs -7.5 @ -110",
      "slip_image_url": "/uploads/betting_slips/abc123.jpg"
    }
    ```
    
    **Note:** 
    - Requires OpenAI API key to be configured
    - Only captains and moderators can upload slips
    - Image should be clear and readable for best results
    """
    try:
        # Validate pick_entity_type
        if pick_entity_type not in ["team", "player"]:
            return create_response(
                status_code=400,
                status="error",
                message="pick_entity_type must be either 'team' or 'player'",
                data=None
            )
        
        # Validate file type
        if not slip_image.content_type or not slip_image.content_type.startswith('image/'):
            return create_response(
                status_code=400,
                status="error",
                message="Only image files are allowed",
                data=None
            )
        
        service = get_club_picks_service()
        
        # Analyze the betting slip
        extracted_data = await service.analyze_betting_slip(
            user_id=current_user["user_id"],
            club_id=club_id,
            pick_entity_type=pick_entity_type,
            slip_image=slip_image
        )
        
        return create_response(
            status_code=200,
            status="success",
            message="Betting slip analyzed successfully",
            data=extracted_data
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error uploading slip: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error uploading slip: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to upload and analyze slip: {str(e)}",
            data=None
        )


@router.post("/enhance-reasoning")
async def enhance_reasoning_text(
    reasoning: str = Form(..., description="Reasoning text to enhance"),
    current_user: dict = Depends(get_current_user)
):
    """
    Enhance reasoning text using OpenAI API.
    
    This endpoint takes text with incorrect grammar or poor readability and
    enhances it while maintaining the original meaning.
    
    **Form Data:**
    - `reasoning`: Text to enhance (required)
    
    **Features:**
    - Fixes grammar and spelling errors
    - Improves readability and clarity
    - Maintains the original meaning
    - Generates different variations each time while preserving meaning
    
    **Returns:**
    - Original reasoning text
    - Enhanced reasoning text
    
    **Example Response:**
    ```json
    {
      "original_reasoning": "this team is very good they will win",
      "enhanced_reasoning": "This team is very good and they will win."
    }
    ```
    
    **Note:** 
    - Requires OpenAI API key to be configured
    - Returns enhanced text only (does not update database)
    """
    try:
        service = get_club_picks_service()
        
        # Enhance the reasoning text using OpenAI
        result = await service.enhance_reasoning_text(
            reasoning=reasoning
        )
        
        return create_response(
            status_code=200,
            status="success",
            message="Reasoning text enhanced successfully",
            data=result
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error enhancing reasoning: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error enhancing reasoning: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to enhance reasoning: {str(e)}",
            data=None
        )