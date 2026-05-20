"""
My Picks Routes - API endpoints for user's picks based on role and club memberships
"""

from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import Optional
from datetime import datetime
import logging
import math

from .my_picks_service import get_my_picks_service
from core.auth.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/my-picks", tags=["My Picks"])


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


@router.get("/")
async def get_my_picks(
    status_filter: Optional[str] = Query(None, description="Filter by status (pending/completed)"),
    pick_type_filter: Optional[str] = Query(None, description="Filter by pick type (moneyline, parlay, spread, etc.) - Case insensitive"),
    result_filter: Optional[str] = Query(None, description="Filter by result (pending/win/loss)"),
    sport_league_filter: Optional[str] = Query(None, description="Filter by sport or league (searches both fields) - Case insensitive"),
    date_from: Optional[datetime] = Query(None, description="Filter picks by creation date from this date (ISO 8601 format)"),
    date_to: Optional[datetime] = Query(None, description="Filter picks by creation date to this date (ISO 8601 format)"),
    search: Optional[str] = Query(
        None,
        description="Case-insensitive search across club name, sport, league, pick_type, player_name, team names, and parlay legs",
    ),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get user's picks based on their role and club memberships.
    
    **User Role Logic:**
    - **Captain**: Gets picks from all clubs they created + picks from moderators in those clubs
    - **Moderator**: Gets picks from clubs they moderate + picks from captains and other moderators in those clubs
    - **Member**: Gets picks from clubs they joined (paid/trial) where captains or moderators submitted picks
    
    **Query Parameters:**
    - `status_filter`: Optional filter by status (pending or completed)
    - `pick_type_filter`: Optional filter by pick type (moneyline, parlay, spread, etc.)
    - `result_filter`: Optional filter by result (pending, win, loss)
    - `date_from`: Optional filter picks from this date (ISO 8601 format)
    - `date_to`: Optional filter picks to this date (ISO 8601 format)
    - `search`: Optional case-insensitive search across club name, sport, league, pick type, player name, team names, and parlay legs
    - `page`: Page number (default: 1)
    - `limit`: Items per page (default: 20, max: 100)
    
    **Returns:**
    - List of picks with pagination information
    - User's role and number of clubs they have access to
    
    **Example Response:**
    ```json
    {
      "status": "success",
      "message": "Retrieved 15 pick(s) for user",
      "data": {
        "picks": [
          {
            "id": "pick123",
            "club_id": "elite-bettors",
            "club_name": "Elite Bettors Club",
            "user_role_in_club": "captain",
            "bet_source": "live-support",
            "submitted_by": "user456",
            "submitted_by_role": "moderator",
            "sport": "Basketball",
            "league": "NBA",
            "pick_entity_type": "team",
            "team1": "Lakers",
            "team2": "Warriors",
            "match_datetime": "2024-01-15T20:00:00Z",
            "platform": "DraftKings",
            "pick_type": "moneyline",
            "status": "pending",
            "reasoning": "Lakers at home with better record",
            "result": null,
            "bet_logo": "https://example.com/bet-logo.png",
            "created_at": "2024-01-14T10:30:00Z",
            "updated_at": "2024-01-14T10:30:00Z"
          }
        ],
        "total": 15,
        "page": 1,
        "limit": 20,
        "total_pages": 1,
        "user_role": "Captain",
        "clubs_count": 3
      }
    }
    ```
    """
    try:
        import time
        start_time = time.time()
        logger.info(f"🚀 Starting get_my_picks API for user {current_user['user_id']}")
        
        service = get_my_picks_service()
        service_start_time = time.time()
        
        result = await service.get_my_picks(
            user_id=current_user["user_id"],
            status_filter=status_filter,
            pick_type_filter=pick_type_filter,
            result_filter=result_filter,
            sport_league_filter=sport_league_filter,
            date_from=date_from,
            date_to=date_to,
            search=search,
            page=page,
            limit=limit
        )
        
        service_end_time = time.time()
        logger.info(f"⏱️ Service call took {service_end_time - service_start_time:.3f}s")
        
        # Helper function to format datetime
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, str):
                return dt
            return dt.isoformat() + "Z" if dt.tzinfo else dt.isoformat() + "+00:00"
        
        # Format picks for response
        formatted_picks = []
        for pick in result["picks"]:
            pick_type = pick.get("pick_type", "").lower()
            
            # For Parlay picks, populate top-level fields from first parlay pick
            if pick_type == "parlay" and pick.get("parlay_picks") and len(pick.get("parlay_picks", [])) > 0:
                first_parlay_pick = pick["parlay_picks"][0]
                formatted_pick = {
                    "id": pick["_id"],
                    "club_id": pick["club_id"],
                    "club_name": pick.get("club_name"),
                    "bet_source": pick.get("bet_source"),
                    "user_role_in_club": pick.get("user_role_in_club"),
                    "submitted_by": pick["submitted_by"],
                    "submitted_by_role": pick["submitted_by_role"],
                    # Populate from first parlay pick
                    "sport": first_parlay_pick.get("sport"),
                    "league": first_parlay_pick.get("league"),
                    "pick_entity_type": first_parlay_pick.get("pick_entity_type"),
                    "team1": first_parlay_pick.get("team1"),
                    "team2": first_parlay_pick.get("team2"),
                    "player_name": first_parlay_pick.get("player_name"),
                    "match_datetime": format_datetime(first_parlay_pick.get("match_datetime")),
                    "platform": pick.get("platform"),  # Platform from top level (if exists)
                    "pick_type": pick["pick_type"],
                    "status": pick["status"],
                    "reasoning": pick.get("reasoning"),
                    "result": pick.get("result"),
                    "bet_logo": pick.get("bet_logo"),
                    "parlay_picks": pick.get("parlay_picks"),  # Include full parlay_picks array
                    "created_at": format_datetime(pick.get("created_at")),
                    "updated_at": format_datetime(pick.get("updated_at"))
                }
            else:
                # For non-Parlay picks, use standard format
                formatted_pick = {
                    "id": pick["_id"],
                    "club_id": pick["club_id"],
                    "club_name": pick.get("club_name"),
                      "bet_source": pick.get("bet_source"),
                    "user_role_in_club": pick.get("user_role_in_club"),
                    "submitted_by": pick["submitted_by"],
                    "submitted_by_role": pick["submitted_by_role"],
                    "sport": pick.get("sport"),
                    "league": pick.get("league"),
                    "pick_entity_type": pick.get("pick_entity_type"),
                    "team1": pick.get("team1"),
                    "team2": pick.get("team2"),
                    "player_name": pick.get("player_name"),
                    "match_datetime": format_datetime(pick.get("match_datetime")),
                    "platform": pick.get("platform"),
                    "pick_type": pick["pick_type"],
                    "status": pick["status"],
                    "reasoning": pick.get("reasoning"),
                    "result": pick.get("result"),
                    "bet_logo": pick.get("bet_logo"),
                    "parlay_picks": pick.get("parlay_picks"),  # Include parlay_picks if exists (for consistency)
                    "created_at": format_datetime(pick.get("created_at")),
                    "updated_at": format_datetime(pick.get("updated_at"))
                }
            formatted_picks.append(formatted_pick)
        
        response_data = {
            "picks": formatted_picks,
            "total": result["total"],
            "page": result["page"],
            "limit": result["limit"],
            "total_pages": result["total_pages"],
            "user_role": result["user_role"],
            "clubs_count": result["clubs_count"]
        }
        
        total_time = time.time() - start_time
        logger.info(f"✅ API completed in {total_time:.3f}s - Retrieved {len(formatted_picks)} picks from {result['clubs_count']} clubs")
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Retrieved {len(formatted_picks)} pick(s) for user",
            data=response_data
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error getting my picks: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error getting my picks: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to get picks: {str(e)}",
            data=None
        )


@router.get("/export-csv")
async def export_my_picks_csv(
    status_filter: Optional[str] = Query(None, description="Filter by status (pending/completed)"),
    pick_type_filter: Optional[str] = Query(None, description="Filter by pick type (moneyline, parlay, spread, etc.) - Case insensitive"),
    result_filter: Optional[str] = Query(None, description="Filter by result (pending/win/loss)"),
    sport_league_filter: Optional[str] = Query(None, description="Filter by sport or league (searches both fields) - Case insensitive"),
    date_from: Optional[datetime] = Query(None, description="Filter picks by creation date from this date (ISO 8601 format)"),
    date_to: Optional[datetime] = Query(None, description="Filter picks by creation date to this date (ISO 8601 format)"),
    search: Optional[str] = Query(None, description="Search by pick_type, club_name, or league"),
    current_user: dict = Depends(get_current_user)
):
    """
    Export user's picks to CSV format.
    
    **User Role Logic:**
    - **Captain**: Exports picks from all clubs they created + picks from moderators in those clubs
    - **Moderator**: Exports picks from clubs they moderate + picks from captains and other moderators in those clubs
    - **Member**: Exports picks from clubs they joined (paid/trial) where captains or moderators submitted picks
    
    **Query Parameters:**
    - `status_filter`: Optional filter by status (pending or completed)
    - `pick_type_filter`: Optional filter by pick type (moneyline, parlay, spread, etc.)
    - `result_filter`: Optional filter by result (pending, win, loss)
    - `date_from`: Optional filter picks from this date (ISO 8601 format)
    - `date_to`: Optional filter picks to this date (ISO 8601 format)
    - `search`: Optional case-insensitive search across club name, sport, league, pick type, player name, team names, and parlay legs
    
    **CSV Columns:**
    - Club Name
    - League
    - Pick Type
    - Status
    - Result
    - Player Name
    - Team 1
    - Team 2
    
    **Returns:**
    - CSV file download with user's picks data
    
    **Example Usage:**
    ```
    GET /api/v1/my-picks/export-csv?status_filter=pending&date_from=2024-01-01T00:00:00Z
    ```
    """
    try:
        from fastapi.responses import Response
        
        service = get_my_picks_service()
        
        # Get CSV content
        csv_content = await service.export_my_picks_csv(
            user_id=current_user["user_id"],
            status_filter=status_filter,
            pick_type_filter=pick_type_filter,
            result_filter=result_filter,
            sport_league_filter=sport_league_filter,
            date_from=date_from,
            date_to=date_to,
            search=search
        )
        
        # Generate filename with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"my_picks_export_{timestamp}.csv"
        
        # Return CSV file as response
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8"
            }
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error exporting picks to CSV: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error exporting picks to CSV: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to export picks: {str(e)}",
            data=None
        )


@router.get("/{pick_id}")
async def get_my_pick_by_id(
    pick_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a specific pick by ID based on user's role and club memberships.
    
    **User Role Logic:**
    - **Captain**: Can access picks from all clubs they created + picks from moderators in those clubs
    - **Moderator**: Can access picks from clubs they moderate + picks from captains and other moderators in those clubs
    - **Member**: Can access picks from clubs they joined (paid/trial) where captains or moderators submitted picks
    
    **Parameters:**
    - `pick_id`: Pick ID to retrieve
    
    **Returns:**
    - Pick details with club information and user's role in that club
    
    **Example Response:**
    ```json
    {
      "status": "success",
      "message": "Pick retrieved successfully",
      "data": {
        "id": "pick123",
        "club_id": "elite-bettors",
        "club_name": "Elite Bettors Club",
        "user_role_in_club": "captain",
        "submitted_by": "user456",
        "submitted_by_role": "moderator",
        "sport": "Basketball",
        "league": "NBA",
        "pick_entity_type": "team",
        "team1": "Lakers",
        "team2": "Warriors",
        "player_name": null,
        "match_datetime": "2024-01-15T20:00:00Z",
        "platform": "DraftKings",
        "pick_type": "moneyline",
        "status": "pending",
        "reasoning": "Lakers at home with better record",
        "result": null,
        "created_at": "2024-01-14T10:30:00Z",
        "updated_at": "2024-01-14T10:30:00Z"
      }
    }
    ```
    """
    try:
        service = get_my_picks_service()
        
        pick = await service.get_my_pick_by_id(
            user_id=current_user["user_id"],
            pick_id=pick_id
        )
        
        # Format pick for response
        formatted_pick = {
            "id": pick["_id"],
            "club_id": pick["club_id"],
            "club_name": pick.get("club_name"),
            "user_role_in_club": pick.get("user_role_in_club"),
              "bet_source": pick.get("bet_source"),
            "submitted_by": pick["submitted_by"],
            "submitted_by_role": pick["submitted_by_role"],
            "sport": pick["sport"],
            "league": pick["league"],
            "pick_entity_type": pick["pick_entity_type"],
            "team1": pick.get("team1"),
            "team2": pick.get("team2"),
            "player_name": pick.get("player_name"),
            "match_datetime": pick["match_datetime"],
            "platform": pick["platform"],
            "pick_type": pick["pick_type"],
            "status": pick["status"],
            "reasoning": pick.get("reasoning"),
            "result": pick.get("result"),
            "created_at": pick["created_at"],
            "updated_at": pick["updated_at"]
        }
        
        return create_response(
            status_code=200,
            status="success",
            message="Pick retrieved successfully",
            data=formatted_pick
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error getting pick by ID: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error getting pick by ID: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to get pick: {str(e)}",
            data=None
        )


@router.get("/summary")
async def get_my_picks_summary(
    current_user: dict = Depends(get_current_user)
):
    """
    Get summary statistics for user's picks.
    
    **Returns:**
    - Total picks count
    - Pending picks count
    - Completed picks count
    - Wins and losses count
    - Win percentage
    - Number of clubs user has access to
    - User's role
    
    **Example Response:**
    ```json
    {
      "status": "success",
      "message": "Picks summary retrieved successfully",
      "data": {
        "total_picks": 45,
        "pending_picks": 12,
        "completed_picks": 33,
        "wins": 22,
        "losses": 11,
        "win_percentage": 66.67,
        "clubs_count": 3,
        "user_role": "Captain"
      }
    }
    ```
    """
    try:
        service = get_my_picks_service()
        
        summary = await service.get_my_picks_summary(
            user_id=current_user["user_id"]
        )
        
        return create_response(
            status_code=200,
            status="success",
            message="Picks summary retrieved successfully",
            data=summary
        )
        
    except HTTPException as e:
        logger.error(f"HTTP error getting picks summary: {e.detail}")
        return create_response(
            status_code=e.status_code,
            status="error",
            message=e.detail,
            data=None
        )
    except Exception as e:
        logger.error(f"Error getting picks summary: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to get picks summary: {str(e)}",
            data=None
        )


@router.get("/debug/clubs")
async def debug_my_clubs(
    current_user: dict = Depends(get_current_user)
):
    """
    Debug endpoint to check user's club access and structure.
    
    **Returns:**
    - User's role
    - List of clubs user has access to
    - Club details and user's role in each club
    """
    try:
        from bson import ObjectId
        
        service = get_my_picks_service()
        
        # Get user details
        user = await service.users_collection.find_one({"_id": ObjectId(current_user["user_id"])})
        
        if not user:
            return create_response(
                status_code=404,
                status="error",
                message="User not found",
                data=None
            )
        
        user_role = user.get("role", "Member")
        
        # Get user's clubs
        user_clubs = await service._get_user_clubs(current_user["user_id"], user_role)
        
        # Format clubs for response
        formatted_clubs = []
        for club in user_clubs:
            formatted_clubs.append({
                "club_id": club["club_id"],
                "club_name": club["club_name"],
                "user_role_in_club": club["user_role_in_club"],
                "club_status": club["club_data"].get("status"),
                "club_is_active": club["club_data"].get("is_active"),
                "captain_id": club["club_data"].get("captain_id"),
                "moderators_count": len(club["club_data"].get("moderators", [])),
                "detailed_moderators_count": len(club["club_data"].get("detailed_moderators", []))
            })
        
        debug_data = {
            "user_id": current_user["user_id"],
            "user_role": user_role,
            "clubs_count": len(user_clubs),
            "clubs": formatted_clubs
        }
        
        return create_response(
            status_code=200,
            status="success",
            message="Debug info retrieved successfully",
            data=debug_data
        )
        
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Debug failed: {str(e)}",
            data=None
        )
