from fastapi import APIRouter, HTTPException,status ,Query,Depends, WebSocket, WebSocketDisconnect, Request
from core.api_client import fetch_from_sports_api
from core.config import settings
# from core.sports_mqtt_client import get_sports_mqtt_client, initialize_sports_mqtt
from core.socket import socket_manager
from typing import Optional, Dict, Set
from datetime import datetime, timezone
from bson import ObjectId
import logging
import asyncio
import threading
from services.auth.utils import get_current_user
from fastapi.responses import JSONResponse

from fastapi.encoders import jsonable_encoder


current_user: dict = Depends(get_current_user)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/sports",
    tags=["Sports"]
)

# Debug: Print when module loads
print("✅ Sports routes module loaded")
print(f"✅ Router prefix: {router.prefix}")

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
def get_match_result(score_data: list):
    """
    Parse score data and calculate match result
    
    Args:
        score_data: The 'score' array from TheSports.com API
        Example: ["match_id", 6, 0, [31, 22, 26, 0, 0], [18, 20, 11, 0, 0]]
        
    Returns:
        dict with status, home_total, away_total, and result (if finished)
    """
    if not isinstance(score_data, list) or len(score_data) < 5:
        return {"status": "Invalid", "home_total": 0, "away_total": 0}
    
    match_status = score_data[1] if len(score_data) > 1 else 0
    home_scores = score_data[3] if len(score_data) > 3 and isinstance(score_data[3], list) else [0, 0, 0, 0, 0]
    away_scores = score_data[4] if len(score_data) > 4 and isinstance(score_data[4], list) else [0, 0, 0, 0, 0]
    
    home_total = sum(home_scores)
    away_total = sum(away_scores)
    
    # Match status codes: 0=Not Started, 1-4=Quarters, 5=Overtime, 6=Finished, 7=Postponed, 8=Cancelled
    status_map = {
        0: "Not Started",
        1: "First Quarter",
        2: "Second Quarter",
        3: "Third Quarter",
        4: "Fourth Quarter",
        5: "Overtime",
        6: "Finished",
        7: "Postponed",
        8: "Cancelled"
    }
    
    status_text = status_map.get(match_status, "Unknown")
    
    result = {
        "status": status_text,
        "status_code": match_status,
        "home_total": home_total,
        "away_total": away_total,
        "home_quarter_scores": home_scores,
        "away_quarter_scores": away_scores
    }
    
    # Only determine result if match is finished
    if match_status == 6:  # Finished
        if home_total > away_total:
            result["result"] = "Home Win"
        elif away_total > home_total:
            result["result"] = "Away Win"
        else:
            result["result"] = "Draw"
    
    return result


async def update_pick_result_in_db(match_id: str, match_result: dict):
    """
    Update club_picks in database with match result
    
    Args:
        match_id: Match ID from TheSports API
        match_result: Result dict from get_match_result()
    """
    try:
        from services.club.db import get_database
        from services.admin.db import club_picks_collection
        
        # Only update if match is finished
        if match_result.get("status_code") != 6:
            return
        
        # Find all picks for this match_id
        picks = await club_picks_collection.find({"match_id": match_id}).to_list(length=None)
        
        if not picks:
            logger.debug(f"No picks found for match_id: {match_id}")
            return
        
        # Determine win/loss based on bet_for and match result
        result_value = match_result.get("result")
        home_total = match_result.get("home_total")
        away_total = match_result.get("away_total")
        if not result_value:
            return
        
        # Update each pick
        for pick in picks:
            update_data = {
                "status": "completed",
                "updated_at": datetime.now(),
                "home_total": home_total,
                "away_total": away_total
            }
            
            # Determine if pick won or lost
            bet_for = pick.get("bet_for") or pick.get("bet_on_team")
            team1 = pick.get("team1")
            team2 = pick.get("team2")
            
            # Simple logic: if bet_for matches the winning team, it's a win
            if bet_for and result_value:
                if "Home Win" in result_value and bet_for == team1:
                    update_data["result"] = "win"
                elif "Away Win" in result_value and bet_for == team2:
                    update_data["result"] = "win"
                elif "Draw" in result_value:
                    # For draws, you might want to mark as loss or handle differently
                    update_data["result"] = "loss"
                else:
                    update_data["result"] = "loss"
            else:
                # If we can't determine, mark as loss by default
                update_data["result"] = "loss"
            
            # Update the pick
            await club_picks_collection.update_one(
                {"_id": pick["_id"]},
                {"$set": update_data}
            )
            
            logger.info(f"Updated pick {pick['_id']} for match {match_id}: {update_data['result']}")
    
    except Exception as e:
        logger.error(f"Error updating pick result in database: {str(e)}")


# ============================================================================
@router.get("/match/live-scores/{match_id}")
async def get_live_match_scores(
    match_id: str,
    sport: str = Query("basketball", description="Sport name (default: basketball)"),
):
    """
    Get live match scores from TheSports API.
    Fetches live scores and automatically updates database with results.
    
    **Parameters:**
    - `match_id`: Match ID from TheSports API (required)
    - `sport`: Sport name (default: basketball)
    
    **Returns:**
    - Live match scores with home/away totals
    - Match status and result (if finished)
    - Automatically updates database when match finishes
    """
    try:
        # Fetch live match details from TheSports API
        endpoint = f"{sport}/match/detail_live"
        data = await fetch_from_sports_api(endpoint, extra_params={"id": match_id})
        
        # Extract results
        if isinstance(data, dict):
            results = data.get("results", data.get("data", []))
        elif isinstance(data, list):
            results = data
        else:
            results = []
        
        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"No live match found for match_id: {match_id}"
            )
        
        # Get the first result (should be the match)
        match_data = results[0] if isinstance(results, list) else results
        
        # Extract score data
        score_data = match_data.get("score", [])
        timer_data = match_data.get("timer", [])
        stats_data = match_data.get("stats", [])
        
        # Parse score and calculate result
        match_result = get_match_result(score_data)
        
        # Update database if match is finished
        if match_result.get("status_code") == 6:
            await update_pick_result_in_db(match_id, match_result)
        
        # Build response
        response_data = {
            "match_id": match_id,
            "sport": sport,
            "match_result": match_result,
            "timer": timer_data,
            "stats": stats_data,
            "raw_data": match_data
        }
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Live match scores fetched successfully.",
            data=response_data,
        )
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.exception(f"Error fetching live match scores: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch live match scores: {str(e)}"
        )


# @router.get("/live-bets/{club_name_based_id}")
# async def get_live_bets_by_club(
#     club_name_based_id: str,
#     chat_user=Depends(get_current_user),
# ):
#     """
#     Get all live bets submitted by the Captain for a specific club (club_name_based_id)
#     where bet_source = "live-support". Includes live match scores.
#     """

#     try:
#         from services.club.db import get_database
#         logger.info(f"Fetching live bets for club: {club_name_based_id}")

#         db = await get_database()
#         club_picks_collection = db["club_picks"]
#         users_collection = db["users"]

#         # Query club_picks for live bets
#         club_picks_cursor = club_picks_collection.find(
#             {
#                 "club_id": club_name_based_id,
#                 "bet_source": "live-support",
#             }
#         )

#         club_picks = await club_picks_cursor.to_list(length=None)

#         if not club_picks:
#             return create_response(
#                 status_code=status.HTTP_200_OK,
#                 status="success",
#                 message="No live bets found for this club.",
#                 data=[],
#             )

#         response_data = []
#         for pick in club_picks:
#             submitted_by_id = pick.get("submitted_by")

#             # Get user (captain/moderator) info from users table
#             user_info = await users_collection.find_one(
#                 {"_id": ObjectId(submitted_by_id)},
#                 {"full_name": 1, "avatar_url": 1},
#             )
            
#             # Get live match scores if match_id exists
#             live_scores = None
#             match_id = pick.get("match_id")
#             if match_id:
#                 try:
#                     sport = pick.get("sport", "basketball")
#                     endpoint = f"{sport}/match/detail_live"
#                     match_data = await fetch_from_sports_api(endpoint, extra_params={"id": match_id})
                    
#                     if isinstance(match_data, dict):
#                         results = match_data.get("results", match_data.get("data", []))
#                     elif isinstance(match_data, list):
#                         results = match_data
#                     else:
#                         results = []
                    
#                     if results:
#                         match_info = results[0] if isinstance(results, list) else results
#                         score_data = match_info.get("score", [])
#                         if score_data:
#                             live_scores = get_match_result(score_data)
#                 except Exception as e:
#                     logger.warning(f"Could not fetch live scores for match {match_id}: {str(e)}")

#             response_data.append({
#                 "submitted_by": str(submitted_by_id),
#                 "submitted_by_role": pick.get("submitted_by_role"),
#                 "captain_name": user_info.get("full_name") if user_info else None,
#                 "captain_avatar_url": user_info.get("avatar_url") if user_info else None,
#                 "pick_entity_type": pick.get("pick_entity_type"),
#                 "team1": pick.get("team1"),
#                 "team2": pick.get("team2"),
#                 "player_name": pick.get("player_name"),
#                 "platform": pick.get("platform"),
#                 "bet_for": pick.get("bet_for"),
#                 "match_id": match_id,
#                 "match_datetime": pick.get("match_datetime"),
#                 "status": pick.get("status"),
#                 "result": pick.get("result"),
#                 "live_scores": live_scores,
#             })

#         return create_response(
#             status_code=status.HTTP_200_OK,
#             status="success",
#             message="Live bets fetched successfully.",
#             data=response_data,
#         )

#     except Exception as e:
#         logger.exception(f"Error fetching live bets: {str(e)}")
#         return create_response(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             status="error",
#             message="Failed to fetch live bets.",
#         )


def calculate_scores(score_data):
    """Compute total home and away scores"""
    try:
        home_total = sum(score_data[3])
        away_total = sum(score_data[4])
        return {"home_total": home_total, "away_total": away_total}
    except Exception:
        return {"home_total": 0, "away_total": 0}

from datetime import datetime,timezone
# from .socket_manager_sport import sio

# IMPORTANT: /live-bets/all must be defined BEFORE /live-bets/{club_name_based_id}
# Otherwise FastAPI will match "all" as a path parameter
@router.get("/live-bets/all")
async def get_all_live_bets_for_user(
    chat_user=Depends(get_current_user),
    sport: Optional[str] = Query(None, description="Filter by sport: basketball or american_football"),
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page (max 100)")
):
    """
    Get live scores for all clubs the user has joined.
    
    Returns live-support bets from all clubs where:
    - User is a member (joined club)
    - User is a captain (created club)
    - User is a moderator (assigned to club)
    
    For each club, fetches all bets with bet_source: "live-support"
    submitted by captains or moderators.
    
    Query Parameters:
    - sport: Optional filter by sport (basketball or american_football)
    - page: Page number (default: 1)
    - page_size: Items per page (default: 20, max: 100)
    """
    import sys
    print("=" * 80, file=sys.stderr, flush=True)
    print("🚀 START: get_all_live_bets_for_user called", file=sys.stderr, flush=True)
    print("=" * 80, file=sys.stderr, flush=True)
    try:
        print(f"🚀 User ID: {chat_user.get('user_id')}, Role: {chat_user.get('role')}", file=sys.stderr, flush=True)
        from services.club.db import get_database
        from services.club.membership_service import get_user_clubs_details
        
        db = await get_database()
        club_picks_collection = db["club_picks"]
        users_collection = db["users"]
        clubs_collection = db["clubs"]
        
        user_id = chat_user["user_id"]
        user_role = chat_user.get("role", "Member")
        print(f"🚀 Processing for user_id: {user_id}, role: {user_role}", file=sys.stderr, flush=True)
        
        # Get all clubs the user has access to
        club_ids = []
        
        if user_role == "Captain":
            # Get clubs created by the user
            clubs_cursor = clubs_collection.find({"captain_id": ObjectId(user_id)})
            clubs = await clubs_cursor.to_list(length=None)
            club_ids = [club.get("name_based_id") for club in clubs if club.get("name_based_id")]
            print(f"✅ Captain {user_id} has {len(club_ids)} clubs", file=sys.stderr, flush=True)
        else:
            # For members/moderators, get clubs from clubs_joined array
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user:
                clubs_joined = user.get("clubs_joined", [])
                import sys
                print(f"🔍 DEBUG: User has {len(clubs_joined)} clubs in clubs_joined array", file=sys.stderr, flush=True)
                
                # Debug: Print first club structure
                if clubs_joined:
                    print(f"🔍 DEBUG: First club structure: {clubs_joined[0]}", file=sys.stderr, flush=True)
                    print(f"🔍 DEBUG: First club keys: {list(clubs_joined[0].keys()) if isinstance(clubs_joined[0], dict) else 'Not a dict'}", file=sys.stderr, flush=True)
                
                # Extract club name_based_id from clubs_joined array
                for idx, club_data in enumerate(clubs_joined):
                    print(f"🔍 DEBUG: Processing club {idx + 1}: {type(club_data)}", file=sys.stderr, flush=True)
                    if isinstance(club_data, dict):
                        # Try to get club_name_based_id first (preferred)
                        name_based_id = club_data.get("club_name_based_id")
                        print(f"🔍 DEBUG: Club {idx + 1} - club_name_based_id: {name_based_id}", file=sys.stderr, flush=True)
                        if name_based_id:
                            if name_based_id not in club_ids:
                                club_ids.append(name_based_id)
                                print(f"✅ Added club_name_based_id: {name_based_id}", file=sys.stderr, flush=True)
                        else:
                            # If name_based_id not in clubs_joined, look it up from clubs collection
                            club_obj_id = club_data.get("club_id")
                            print(f"🔍 DEBUG: Club {idx + 1} - club_id (ObjectId): {club_obj_id}", file=sys.stderr, flush=True)
                            if club_obj_id:
                                try:
                                    club = await clubs_collection.find_one({"_id": ObjectId(club_obj_id)})
                                    if club:
                                        club_name_based = club.get("name_based_id")
                                        print(f"🔍 DEBUG: Found club in DB - name_based_id: {club_name_based}", file=sys.stderr, flush=True)
                                        if club_name_based and club_name_based not in club_ids:
                                            club_ids.append(club_name_based)
                                            print(f"✅ Added club from DB lookup: {club_name_based}", file=sys.stderr, flush=True)
                                    else:
                                        print(f"⚠️ Club not found in DB for ObjectId: {club_obj_id}", file=sys.stderr, flush=True)
                                except Exception as e:
                                    print(f"⚠️ Error looking up club {club_obj_id}: {e}", file=sys.stderr, flush=True)
                                    import traceback
                                    traceback.print_exc()
                    else:
                        # If it's just a string, try to use it directly
                        print(f"🔍 DEBUG: Club {idx + 1} is a string: {club_data}", file=sys.stderr, flush=True)
                        if club_data not in club_ids:
                            club_ids.append(club_data)
                            print(f"✅ Added club as string: {club_data}", file=sys.stderr, flush=True)
                
                print(f"✅ User {user_id} has joined {len(club_ids)} clubs (extracted from clubs_joined)", file=sys.stderr, flush=True)
                print(f"🔍 DEBUG: Final club_ids list: {club_ids}", file=sys.stderr, flush=True)
            
            # Also check if user is a moderator in any clubs
            moderator_clubs_cursor = clubs_collection.find({"moderators": ObjectId(user_id)})
            moderator_clubs = await moderator_clubs_cursor.to_list(length=None)
            moderator_club_ids = [club.get("name_based_id") for club in moderator_clubs if club.get("name_based_id")]
            # Add moderator clubs without duplicates
            for mod_club_id in moderator_club_ids:
                if mod_club_id not in club_ids:
                    club_ids.append(mod_club_id)
            print(f"✅ User {user_id} is moderator in {len(moderator_club_ids)} additional clubs", file=sys.stderr, flush=True)
        
        if not club_ids:
            return create_response(200, "success", "No clubs found for user.", [])
        
        print(f"📊 Total clubs to check: {len(club_ids)}", file=sys.stderr, flush=True)
        print(f"🔍 DEBUG: Club IDs to search: {club_ids}", file=sys.stderr, flush=True)
        
        # Debug: Check if any picks exist for these clubs (without bet_source filter)
        all_picks_cursor = club_picks_collection.find({
            "club_id": {"$in": club_ids}
        })
        all_picks = await all_picks_cursor.to_list(length=None)
        print(f"🔍 DEBUG: Total picks found for these clubs (any bet_source): {len(all_picks)}", file=sys.stderr, flush=True)
        if all_picks:
            print(f"🔍 DEBUG: Sample pick - club_id: {all_picks[0].get('club_id')}, bet_source: {all_picks[0].get('bet_source')}", file=sys.stderr, flush=True)
        
        # Build query filter
        query_filter = {
            "club_id": {"$in": club_ids},
            "bet_source": "live-support"
        }
        
        # Add sport filter if provided
        if sport:
            # Normalize sport name
            sport_lower = sport.lower()
            if sport_lower in ["basketball", "american_football"]:
                query_filter["sport"] = sport_lower
            else:
                return create_response(400, "error", f"Invalid sport filter. Must be 'basketball' or 'american_football'", {
                    "valid_sports": ["basketball", "american_football"]
                })
        
        # Get total count for pagination
        total_count = await club_picks_collection.count_documents(query_filter)
        
        # Get all live-support bets from all user's clubs with pagination
        # Try querying with name_based_id first
        skip = (page - 1) * page_size
        club_picks_cursor = club_picks_collection.find(query_filter).skip(skip).limit(page_size).sort("created_at", -1)
        club_picks = await club_picks_cursor.to_list(length=page_size)
        
        # If no picks found, try querying with ObjectId as fallback
        if not club_picks and club_ids:
            print(f"🔍 DEBUG: No picks found with name_based_id, trying ObjectId lookup...", file=sys.stderr, flush=True)
            # Get ObjectIds for the clubs
            club_object_ids = []
            for club_id in club_ids:
                try:
                    # Try to find club by name_based_id to get ObjectId
                    club = await clubs_collection.find_one({"name_based_id": club_id})
                    if club and club.get("_id"):
                        club_object_ids.append(club.get("_id"))
                except Exception as e:
                    print(f"⚠️ Error getting ObjectId for club {club_id}: {e}", file=sys.stderr, flush=True)
            
            if club_object_ids:
                print(f"🔍 DEBUG: Trying query with ObjectIds: {club_object_ids}", file=sys.stderr, flush=True)
                # Build fallback query filter with ObjectId
                fallback_filter = {
                    "club_object_id": {"$in": club_object_ids},
                    "bet_source": "live-support"
                }
                # Add sport filter if provided
                if sport:
                    sport_lower = sport.lower()
                    if sport_lower in ["basketball", "american_football"]:
                        fallback_filter["sport"] = sport_lower
                
                # Get total count for fallback query
                total_count = await club_picks_collection.count_documents(fallback_filter)
                skip = (page - 1) * page_size
                club_picks_cursor = club_picks_collection.find(fallback_filter).skip(skip).limit(page_size).sort("created_at", -1)
                club_picks = await club_picks_cursor.to_list(length=page_size)
                print(f"🔍 DEBUG: Found {len(club_picks)} picks with ObjectId query", file=sys.stderr, flush=True)
        
        print(f"🔍 DEBUG: Found {len(club_picks)} picks matching query (with bet_source: live-support)", file=sys.stderr, flush=True)
        if club_picks:
            print(f"🔍 DEBUG: Sample pick club_id: {club_picks[0].get('club_id')}", file=sys.stderr, flush=True)
        else:
            # Debug: Check what bet_source values exist
            bet_sources_cursor = club_picks_collection.find({
                "club_id": {"$in": club_ids}
            })
            bet_sources = await bet_sources_cursor.to_list(length=None)
            unique_bet_sources = set(pick.get("bet_source") for pick in bet_sources if pick.get("bet_source"))
            print(f"🔍 DEBUG: Unique bet_source values found: {unique_bet_sources}", file=sys.stderr, flush=True)
        
        if not club_picks:
            debug_data = {
                "clubs_count": len(club_ids),
                "club_ids": club_ids,
                "total_picks_found": len(all_picks) if 'all_picks' in locals() else 0,
                "unique_bet_sources": list(unique_bet_sources) if 'unique_bet_sources' in locals() else [],
                "debug_info": "No picks with bet_source='live-support' found"
            }
            print(f"🔍 DEBUG: Returning debug data: {debug_data}", file=sys.stderr, flush=True)
            return create_response(200, "success", "No live bets found in your clubs.", debug_data)
        
        print(f"📊 Found {len(club_picks)} live-support bets across all clubs", file=sys.stderr, flush=True)
        
        response_data = []
        
        for pick in club_picks:
            match_id = pick.get("match_id")
            submitted_by_id = pick.get("submitted_by")
            club_id = pick.get("club_id")
            live_scores = None
            
            # Get user (captain/moderator) info from users table
            user_info = await users_collection.find_one(
                {"_id": ObjectId(submitted_by_id)},
                {"full_name": 1, "avatar_url": 1},
            )
            
            if match_id:
                sport = pick.get("sport", "basketball")
                endpoint = f"{sport}/match/detail_live"
                match_data = await fetch_from_sports_api(endpoint, extra_params={"id": match_id})
                results = match_data.get("results") or match_data.get("data") or []
                
                if isinstance(results, list) and results:
                    match_info = results[0]
                    score_data = match_info.get("score", [])
                    live_scores = calculate_scores(score_data)
                    
                    # Emit to frontend for this club
                    await socket_manager.sio.emit(
                        "live_score_update",
                        {
                            "club_id": club_id,
                            "match_id": match_id,
                            "live_scores": live_scores,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
            
            response_data.append({
                "club_id": club_id,
                "match_id": match_id,
                "live_scores": live_scores,
                "bet_source": pick.get("bet_source"),
                "result": pick.get("result"),
                "status": pick.get("status"),
                "sport": pick.get("sport"),
                "submitted_by": str(submitted_by_id),
                "submitted_by_role": pick.get("submitted_by_role"),
                "captain_name": user_info.get("full_name") if user_info else None,
                "captain_avatar_url": user_info.get("avatar_url") if user_info else None,
                "pick_entity_type": pick.get("pick_entity_type"),
                "team1": pick.get("team1"),
                "team2": pick.get("team2"),
                "player_name": pick.get("player_name"),
                "platform": pick.get("platform"),
                "bet_for": pick.get("bet_for"),
                "match_datetime": pick.get("match_datetime"),
                "status": pick.get("status"),
                "result": pick.get("result"),
                "player_id": pick.get("player_id"),
                "home_team_id": pick.get("home_team_id"),
                "away_team_id": pick.get("away_team_id"),
                "bet_on_team_id": pick.get("bet_on_team_id"),
                "league_id": pick.get("league_id"),
                "home_logo": pick.get("home_logo"),
                "away_logo": pick.get("away_logo"),
                "pick_type": pick.get("pick_type"),
                "parlay_picks": pick.get("parlay_picks"),
                
            })
        
        # Calculate pagination metadata
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
        
        return create_response(
            200, 
            "success", 
            f"Live bets fetched from {len(club_ids)} club(s).", 
            {
                "clubs_count": len(club_ids),
                "bets_count": len(response_data),
                "total_count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1,
                "sport_filter": sport if sport else None,
                "bets": response_data
            }
        )

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ ERROR in get_all_live_bets_for_user: {str(e)}", file=sys.stderr, flush=True)
        print(f"❌ Traceback: {error_trace}", file=sys.stderr, flush=True)
        logger.exception(f"Error fetching all live bets: {str(e)}")
        return create_response(500, "error", f"Failed to fetch live bets: {str(e)}", {
            "error": str(e),
            "traceback": error_trace
        })

@router.get("/live-bets/{club_name_based_id}")
async def get_live_bets_by_club(
    club_name_based_id: str,
    sport: Optional[str] = Query(
        None, description="Optional sport filter: basketball or american_football"
    ),
    chat_user=Depends(get_current_user),
):
    try:
        from services.club.db import get_database
        db = await get_database()
        club_picks_collection = db["club_picks"]
        users_collection = db["users"]

        query_filter = {
            "club_id": club_name_based_id,
            "bet_source": "live-support",
        }

        if sport:
            sport_lower = sport.lower()
            if sport_lower in ["basketball", "american_football"]:
                query_filter["sport"] = sport_lower
            else:
                return create_response(
                    400,
                    "error",
                    "Invalid sport filter. Must be 'basketball' or 'american_football'",
                    {"valid_sports": ["basketball", "american_football"]},
                )

        club_picks_cursor = club_picks_collection.find(query_filter)
        club_picks = await club_picks_cursor.to_list(length=None)

        if not club_picks:
            return create_response(200, "success", "No live bets found.", [])

        response_data = []
        print(f"Club picks: {club_picks}")
        for pick in club_picks:
            match_id = pick.get("match_id")
            print(f"Match id: {match_id}")
            submitted_by_id = pick.get("submitted_by")
            live_scores = None
            print(f"Live scores: {live_scores}")
            # Get user (captain/moderator) info from users table
            user_info = await users_collection.find_one(
                {"_id": ObjectId(submitted_by_id)},
                {"full_name": 1, "avatar_url": 1},
            )
            
            print(f"Match id: {match_id}")
            if match_id:
                print("kyayayyaayay")
                sport = pick.get("sport", "basketball")

                endpoint = f"{sport}/match/detail_live"
                print(f"Endpoint: {endpoint}")
                match_data = await fetch_from_sports_api(endpoint, extra_params={"id": match_id})
                print(f"Match data: {match_data}")
                results = match_data.get("results") or match_data.get("data") or []
                if isinstance(results, list) and results:
                    match_info = results[0]
                    score_data = match_info.get("score", [])
                    print(f"Score data: {score_data}")
                    live_scores = calculate_scores(score_data)

                    # Emit to frontend
                    await socket_manager.sio.emit(
                        "live_score_update",
                        {
                            "club_id": club_name_based_id,
                            "match_id": match_id,
                            "live_scores": live_scores,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        # room=club_name_based_id,
                    )

            response_data.append({
                "match_id": match_id,
                "live_scores": live_scores,
                "result": pick.get("result"),
                "status": pick.get("status"),
                "sport": pick.get("sport"),
                  "submitted_by": str(submitted_by_id),
                "submitted_by_role": pick.get("submitted_by_role"),
                "captain_name": user_info.get("full_name") if user_info else None,
                "captain_avatar_url": user_info.get("avatar_url") if user_info else None,
                "pick_entity_type": pick.get("pick_entity_type"),
                "team1": pick.get("team1"),
                "team2": pick.get("team2"),
                "player_name": pick.get("player_name"),
                "platform": pick.get("platform"),
                "bet_for": pick.get("bet_for"),
                "match_id": match_id,
                "match_datetime": pick.get("match_datetime"),
                "status": pick.get("status"),
                "result": pick.get("result"),
                "player_id": pick.get("player_id"),
                "home_logo": pick.get("home_logo"),
                "away_logo": pick.get("away_logo"),
                "home_team_id": pick.get("home_team_id"),
                "away_team_id": pick.get("away_team_id"),
                "bet_on_team_id": pick.get("bet_on_team_id"),
                "league_id": pick.get("league_id"),
                "pick_type": pick.get("pick_type"),
                "parlay_picks": pick.get("parlay_picks"),
            })

        return create_response(200, "success", "Live bets fetched.", response_data)

    except Exception as e:
        logger.exception(f"Error fetching live bets: {str(e)}")
        return create_response(500, "error", "Failed to fetch live bets.")

@router.get("/pick/detail/{match_id}")
async def get_pick_detail_by_match_id(
    match_id: str,
    club_id: Optional[str] = Query(None, description="Optional club ID to filter picks"),
    chat_user=Depends(get_current_user)
):
    """
    Get detailed pick information based on match_id.
    
    Returns detailed information about all picks associated with a specific match_id,
    including live scores, user information, and all pick details.
    
    **Parameters:**
    - `match_id`: Match ID from sports API (required)
    - `club_id`: Optional club ID to filter picks by club
    
    **Returns:**
    - List of detailed pick information including:
      - match_id, live_scores, result, status, sport
      - submitted_by, submitted_by_role, captain_name, captain_avatar_url
      - pick_entity_type, team1, team2, player_name
      - platform, bet_for, match_datetime
      - player_id, league_id (if available)
    """
    try:
        from services.club.db import get_database
        
        db = await get_database()
        club_picks_collection = db["club_picks"]
        users_collection = db["users"]
        
        # Build query filter
        query_filter = {"match_id": match_id}
        
        # Add club_id filter if provided
        if club_id:
            query_filter["club_id"] = club_id
        
        # Find all picks with this match_id
        picks_cursor = club_picks_collection.find(query_filter)
        picks = await picks_cursor.to_list(length=None)
        
        if not picks:
            return create_response(200, "success", f"No picks found for match_id: {match_id}", [])
        
        response_data = []
        
        for pick in picks:
            match_id_from_pick = pick.get("match_id")
            submitted_by_id = pick.get("submitted_by")
            club_id_from_pick = pick.get("club_id")
            live_scores = None
            
            # Get user (captain/moderator) info from users table
            user_info = await users_collection.find_one(
                {"_id": ObjectId(submitted_by_id)},
                {"full_name": 1, "avatar_url": 1},
            )
            
            # Fetch live scores if match_id is available
            if match_id_from_pick:
                try:
                    sport = pick.get("sport", "basketball")
                    endpoint = f"{sport}/match/detail_live"
                    match_data = await fetch_from_sports_api(endpoint, extra_params={"id": match_id_from_pick})
                    results = match_data.get("results") or match_data.get("data") or []
                    
                    if isinstance(results, list) and results:
                        match_info = results[0]
                        score_data = match_info.get("score", [])
                        live_scores = calculate_scores(score_data)
                except Exception as e:
                    logger.warning(f"Could not fetch live scores for match_id {match_id_from_pick}: {e}")
            
            # Format datetime helper
            def format_datetime(dt):
                if dt is None:
                    return None
                if isinstance(dt, str):
                    return dt
                return dt.isoformat() + "Z" if dt.tzinfo else dt.isoformat() + "+00:00"
            
            # Build response with all fields from lines 727-747
            pick_detail = {
                "club_id": club_id_from_pick,
                "match_id": match_id_from_pick,
                "live_scores": live_scores,
                "league_name": pick.get("league_name"),
                "result": pick.get("result"),
                "status": pick.get("status"),
                "sport": pick.get("sport"),
                "submitted_by": str(submitted_by_id),
                "submitted_by_role": pick.get("submitted_by_role"),
                "captain_name": user_info.get("full_name") if user_info else None,
                "captain_avatar_url": user_info.get("avatar_url") if user_info else None,
                "pick_entity_type": pick.get("pick_entity_type"),
                "team1": pick.get("team1"),
                "team2": pick.get("team2"),
                "player_name": pick.get("player_name"),
                "player_id": pick.get("player_id"),
                "league_id": pick.get("league_id"),
                "platform": pick.get("platform"),
                "bet_for": pick.get("bet_for"),
                "match_datetime": format_datetime(pick.get("match_datetime")),
                "pick_type": pick.get("pick_type"),
                "bet_source": pick.get("bet_source"),
                "reasoning": pick.get("reasoning"),
                "bet_logo": pick.get("bet_logo"),
                "bet_on_team": pick.get("bet_on_team"),
                "club_name": pick.get("club_name"),
                "created_at": format_datetime(pick.get("created_at")),
                "updated_at": format_datetime(pick.get("updated_at")),
                "parlay_picks": pick.get("parlay_picks"),
                "home_team_id": pick.get("home_team_id"),
                "away_team_id": pick.get("away_team_id"),
                "bet_on_team_id": pick.get("bet_on_team_id"),
                "league_id": pick.get("league_id"),
                "match_id": pick.get("match_id"),
                "home_logo": pick.get("home_logo"),
                "away_logo": pick.get("away_logo"),
                "league": pick.get("league_name"),
            }
            
            response_data.append(pick_detail)
        
        return create_response(
            200,
            "success",
            f"Found {len(response_data)} pick(s) for match_id: {match_id}",
            {
                "match_id": match_id,
                "total_picks": len(response_data),
                "picks": response_data
            }
        )
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.exception(f"Error fetching pick detail: {str(e)}")
        return create_response(500, "error", f"Failed to fetch pick detail: {str(e)}", {
            "error": str(e),
            "traceback": error_trace
        })

@router.get("/live-bets/all-test")
async def test_live_bets_endpoint():
    """Test endpoint without auth to verify route is working"""
    print("=" * 80)
    print("🧪 TEST ENDPOINT HIT - /live-bets/all-test")
    print("=" * 80)
    return {"status": "success", "message": "Test endpoint working", "data": {"test": True}}

# Duplicate endpoint removed - see definition at line 365

@router.get("/test/emit")
async def test_socket_emit():
    """
    Simple test endpoint to check if socket emit is working.
    
    This endpoint broadcasts a test emit to all connected clients.
    
    Example:
    GET /api/v1/sports/test/emit
    """
    try:
        # from .socket_manager_sport import connected_clients
        
        # Get connected clients count
        # total_connected = len(connected_clients)
        
        # Prepare simple test data
        emit_data = {
            "club_id": "test_club",
            "match_id": "test_match_123",
            "live_scores": {
                "home_total": 100,
                "away_total": 95
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "test": True
        }
        
        print(f"📊 Test emit request:")
        # print(f"   - Total connected clients: {total_connected}")
        print(f"   - Emit data: {emit_data}")
        
        # Try to emit
        # if total_connected > 0:
        try:
            await socket_manager.sio.emit(
                "live_score_updatesss",
                emit_data
            )
            print(f"✅ Successfully emitted test data to all connected clients")
            
            return create_response(
                200,
                "success",
                f"Test emit successful. Emitted to  connected client(s).",
                {
                    "emitted": True,
                    "emit_data": emit_data
                }
            )
        except Exception as emit_error:
            print(f"❌ Error emitting to socket: {emit_error}")
            return create_response(
                500,
                "error",
                f"Failed to emit: {str(emit_error)}",
                {
                    "emitted": False,
                    "error": str(emit_error),
                }
            )
        
            
    except Exception as e:
        logger.exception(f"Error in test emit: {str(e)}")
        return create_response(500, "error", f"Test emit failed: {str(e)}")

@router.get("/config/check")
async def check_sports_config():
    """
    Check if Sports API configuration is loaded correctly.
    Returns masked credentials for security.
    Also checks server's public IP address.
    """
    import httpx
    
    # Get server's public IP
    public_ip = None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get("https://api.ipify.org")
            public_ip = response.text.strip()
    except:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get("https://ifconfig.me/ip")
                public_ip = response.text.strip()
        except:
            public_ip = "Could not determine"
    
    return {
        "api_configured": bool(settings.SPORTS_API_BASE_URL and settings.SPORTS_USER_TOKEN and settings.SPORTS_SECRET_TOKEN),
        "base_url": settings.SPORTS_API_BASE_URL if settings.SPORTS_API_BASE_URL else "NOT SET",
        "user_token": f"{settings.SPORTS_USER_TOKEN[:8]}..." if settings.SPORTS_USER_TOKEN and len(settings.SPORTS_USER_TOKEN) > 8 else "NOT SET",
        "secret_token": f"{settings.SPORTS_SECRET_TOKEN[:8]}..." if settings.SPORTS_SECRET_TOKEN and len(settings.SPORTS_SECRET_TOKEN) > 8 else "NOT SET",
        "server_public_ip": public_ip,
        "message": "All credentials are loaded. Please verify your server's public IP is whitelisted in TheSports API dashboard." if (settings.SPORTS_API_BASE_URL and settings.SPORTS_USER_TOKEN and settings.SPORTS_SECRET_TOKEN) else "Missing credentials in .env file"
    }


# @router.get("/match/live/{sport_name}")
# async def get_live_scores(
#     sport_name: str,
#     competition_id: Optional[str] = Query(None, description="Filter by competition_id (optional)"),
#     match_id: Optional[str] = Query(None, description="Filter by specific match_id (optional)")
# ):
#     """
#     Get live scores/match results (win/loss) for a given sport
    
#     This endpoint uses the detail_live API to fetch current live match scores.
    
#     **Parameters:**
#     - `sport_name`: Sport type (basketball, american_football)
#     - `competition_id`: Optional. Filter by specific competition/league ID
#     - `match_id`: Optional. Filter by specific match ID
    
#     **Example:**
#     - `/api/v1/sports/match/live/basketball`
#     - `/api/v1/sports/match/live/basketball?competition_id=49vjxm8xt4q6odg`
#     - `/api/v1/sports/match/live/basketball?match_id=12345`
#     """
#     try:
#         # Validate sport name
#         if sport_name.lower() not in ["basketball", "american_football"]:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Unsupported sport. Supported: basketball, american_football"
#             )
        
#         # Determine endpoint based on sport
#         if sport_name.lower() == "basketball":
#             endpoint = "basketball/match/detail_live"
#         else:  # american_football
#             endpoint = "american_football/match/detail_live"
        
#         logger.info(f"Fetching live scores for {sport_name}")
#         data = await fetch_from_sports_api(endpoint)
        
#         # Extract matches from response
#         if isinstance(data, dict):
#             matches = data.get("matches", data.get("data", data.get("results", [])))
#         elif isinstance(data, list):
#             matches = data
#         else:
#             matches = []
        
#         # Apply filters if provided
#         if competition_id:
#             competition_id_str = str(competition_id)
#             matches = [
#                 match for match in matches
#                 if isinstance(match, dict) and str(match.get("competition_id") or match.get("competitionId") or match.get("competition", "")) == competition_id_str
#             ]
        
#         if match_id:
#             match_id_str = str(match_id)
#             matches = [
#                 match for match in matches
#                 if isinstance(match, dict) and str(match.get("match_id") or match.get("matchId") or match.get("id", "")) == match_id_str
#             ]
        
#         # Get live updates from MQTT/WebSocket if available
#         mqtt_client = get_sports_mqtt_client()
#         live_updates_applied = 0
#         matches_updated = []
        
#         if mqtt_client.is_connected():
#             # Map sport to MQTT topic
#             sport_topic_map = {
#                 "basketball": "basketball/live",
#                 "american_football": "american_football/live"
#             }
#             topic = sport_topic_map.get(sport_name.lower())
            
#             # Subscribe to topic if not already subscribed (to receive live updates)
#             if topic and topic not in mqtt_client.get_subscribed_topics():
#                 logger.info(f"Subscribing to MQTT topic {topic} for live updates")
#                 mqtt_client.subscribe(topic)
            
#             if topic and topic in mqtt_client.get_subscribed_topics():
#                 # Get latest updates for this topic
#                 latest_updates = mqtt_client.get_latest_updates_for_topic(topic)
                
#                 # Create a map of match_id -> latest update
#                 updates_map = {}
#                 for update in latest_updates:
#                     update_data = update.get("data", {})
#                     # Extract match_id from update
#                     match_id_from_update = (
#                         update_data.get("match_id") or 
#                         update_data.get("matchId") or 
#                         update_data.get("id") or
#                         update_data.get("data", {}).get("match_id") if isinstance(update_data.get("data"), dict) else None
#                     )
#                     if match_id_from_update:
#                         updates_map[str(match_id_from_update)] = update_data
                
#                 # Merge API data with live MQTT updates
#                 for match in matches:
#                     match_dict = match.copy() if isinstance(match, dict) else match
                    
#                     # Extract match_id from match
#                     api_match_id = (
#                         str(match_dict.get("match_id") or 
#                         match_dict.get("matchId") or 
#                         match_dict.get("id") or "")
#                     )
                    
#                     # If we have a live update for this match, merge it
#                     if api_match_id and api_match_id in updates_map:
#                         live_update = updates_map[api_match_id]
#                         # Find the timestamp from the original update
#                         update_timestamp = None
#                         for update in latest_updates:
#                             update_data = update.get("data", {})
#                             update_match_id = (
#                                 update_data.get("match_id") or 
#                                 update_data.get("matchId") or 
#                                 update_data.get("id") or
#                                 update_data.get("data", {}).get("match_id") if isinstance(update_data.get("data"), dict) else None
#                             )
#                             if str(update_match_id) == api_match_id:
#                                 update_timestamp = update.get("timestamp")
#                                 break
                        
#                         # Merge live update data into match data
#                         # Priority: live update > API data (live updates overwrite API data)
#                         match_dict.update(live_update)
#                         match_dict["_live_update"] = True
#                         match_dict["_live_update_timestamp"] = update_timestamp
#                         live_updates_applied += 1
                    
#                     matches_updated.append(match_dict)
                
#                 logger.info(f"Applied {live_updates_applied} live updates from MQTT to matches")
#             else:
#                 # MQTT connected but subscription failed
#                 matches_updated = matches
#         else:
#             # MQTT not connected, use API data only
#             matches_updated = matches
        
#         return {
#             "sport": sport_name.lower(),
#             "live_matches": matches_updated,
#             "total_matches": len(matches_updated),
#             "live_updates_applied": live_updates_applied,
#             "mqtt_connected": mqtt_client.is_connected(),
#             "filters": {
#                 "competition_id": competition_id,
#                 "match_id": match_id
#             }
#         }
        
#     except HTTPException as e:
#         raise e
#     except Exception as e:
#         logger.error(f"Error getting live scores: {str(e)}")
#         raise HTTPException(status_code=500, detail=f"Failed to get live scores: {str(e)}")


@router.get("/matches/{uuid}/details")
async def get_match_details_by_uuid(
    uuid: str,
    sport: str = Query(..., description="Sport name (basketball, american_football, cricket, etc.)"),
    competition_id: Optional[str] = Query(None, description="Competition/League ID. Optional but recommended for better performance.")
):
    """
    Get match details by uuid/match_id
    
    Returns detailed match information including:
    - competition_id, competition_name, competition_short_name
    - match_id
    - home_team (id and name)
    - away_team (id and name)
    - match_time and match_date
    
    **Parameters:**
    - `uuid`: Required. Match UUID/match_id
    - `sport`: Required. Sport type (basketball, american_football, cricket, etc.)
    - `competition_id`: Optional. Competition/League ID. If provided, filters matches faster
    
    **Example:**
    - `/api/v1/sports/matches/318q6nt6dz23mo9/details?sport=basketball&competition_id=zgpxwrx5tdqyk0j`
    - Returns detailed match information
    """
    try:
        # Validate sport name
        sport_lower = sport.lower()
        supported_sports = ["basketball", "american_football", "cricket", "football", "tennis"]
        
        if sport_lower not in supported_sports:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported sport. Supported: {', '.join(supported_sports)}"
            )
        
        # Determine endpoint based on sport
        if sport_lower == "basketball":
            endpoint = "basketball/match/recent/list"
        elif sport_lower == "american_football":
            endpoint = "american_football/match/list"
        elif sport_lower == "cricket":
            endpoint = "cricket/match/recent/list"
        else:
            endpoint = f"{sport_lower}/match/recent/list"
        
        # Fetch all matches from API
        logger.info(f"Fetching matches from API for {sport_lower}, uuid: {uuid}, competition_id: {competition_id}")
        data = await fetch_from_sports_api(endpoint)
        
        # Extract matches from response
        if isinstance(data, dict):
            matches = data.get("matches", data.get("data", data.get("results", [])))
        elif isinstance(data, list):
            matches = data
        else:
            matches = []
        
        if not matches:
            raise HTTPException(
                status_code=404,
                detail=f"No matches found for {sport_lower}"
            )
        
        logger.info(f"Fetched {len(matches)} matches from API")
        
        # Filter matches by competition_id if provided (for faster lookup)
        # For american_football, matches use unique_tournament_id instead of competition_id
        if competition_id:
            competition_id_str = str(competition_id)
            if sport_lower == "american_football":
                matches = [
                    match for match in matches
                    if isinstance(match, dict) and str(match.get("unique_tournament_id") or match.get("uniqueTournamentId") or match.get("competition_id") or match.get("competitionId") or match.get("competition") or (match.get("competition", {}).get("id") if isinstance(match.get("competition"), dict) else None)) == competition_id_str
                ]
            else:
                matches = [
                    match for match in matches
                    if isinstance(match, dict) and str(match.get("competition_id") or match.get("competitionId") or match.get("competition") or (match.get("competition", {}).get("id") if isinstance(match.get("competition"), dict) else None)) == competition_id_str
                ]
        
        # Find match by uuid
        uuid_str = str(uuid)
        detailed_match = None
        
        for match in matches:
            if not isinstance(match, dict):
                continue
            
            match_id = match.get("match_id") or match.get("matchId") or match.get("id") or match.get("uuid")
            if match_id and str(match_id) == uuid_str:
                detailed_match = match
                break
        
        if not detailed_match:
            raise HTTPException(
                status_code=404,
                detail=f"Match with uuid {uuid} not found" + (f" for competition_id {competition_id}" if competition_id else "")
            )
        
        # Get competition_id from match if not provided
        # For american_football, matches use unique_tournament_id instead of competition_id
        if not competition_id:
            if sport_lower == "american_football":
                competition_id = (
                    detailed_match.get("unique_tournament_id") or
                    detailed_match.get("uniqueTournamentId") or
                    detailed_match.get("competition_id") or 
                    detailed_match.get("competitionId") or 
                    detailed_match.get("competition") or
                    (detailed_match.get("competition", {}).get("id") if isinstance(detailed_match.get("competition"), dict) else None)
                )
            else:
                competition_id = (
                    detailed_match.get("competition_id") or 
                    detailed_match.get("competitionId") or 
                    detailed_match.get("competition") or
                    (detailed_match.get("competition", {}).get("id") if isinstance(detailed_match.get("competition"), dict) else None)
                )
        
        competition_id_str = str(competition_id) if competition_id else None
        
        # Fetch competition details to get league name
        competition_name = None
        competition_short_name = None
        if competition_id_str:
            try:
                if sport_lower == "cricket":
                    comp_endpoint = "cricket/competition/list"
                elif sport_lower == "basketball":
                    comp_endpoint = "basketball/competition/list"
                elif sport_lower == "american_football":
                    comp_endpoint = "american_football/unique_tournament/list"
                else:
                    comp_endpoint = f"{sport_lower}/competition/list"
                
                comp_data = await fetch_from_sports_api(comp_endpoint)
                
                if isinstance(comp_data, dict):
                    competitions = comp_data.get("competitions", comp_data.get("data", comp_data.get("results", [])))
                elif isinstance(comp_data, list):
                    competitions = comp_data
                else:
                    competitions = []
                
                # Find competition details
                for comp in competitions:
                    if isinstance(comp, dict):
                        comp_id = comp.get("id") or comp.get("competition_id") or comp.get("competitionId")
                        if comp_id and str(comp_id) == competition_id_str:
                            competition_name = (
                                comp.get("name") or 
                                comp.get("competition_name") or 
                                comp.get("competitionName")
                            )
                            competition_short_name = (
                                comp.get("short_name") or 
                                comp.get("shortName") or 
                                comp.get("competition_short_name")
                            )
                            break
            except Exception as e:
                logger.warning(f"Could not fetch competition details: {str(e)}")
        
        # Try to get competition name from match data if not found
        if not competition_name and detailed_match:
            competition_name = (
                detailed_match.get("competition_name") or 
                detailed_match.get("competitionName") or
                (detailed_match.get("competition", {}).get("name") if isinstance(detailed_match.get("competition"), dict) else None)
            )
            competition_short_name = (
                detailed_match.get("competition_short_name") or
                detailed_match.get("competitionShortName") or
                (detailed_match.get("competition", {}).get("short_name") if isinstance(detailed_match.get("competition"), dict) else None)
            )
        
        # Extract match details
        home_team_id = (
            detailed_match.get("home_team_id") or 
            detailed_match.get("homeTeamId") or
            (detailed_match.get("home_team", {}).get("id") if isinstance(detailed_match.get("home_team"), dict) else None)
        )
        home_team_name = (
            detailed_match.get("home_team_name") or 
            detailed_match.get("homeTeamName") or
            (detailed_match.get("home_team", {}).get("name") if isinstance(detailed_match.get("home_team"), dict) else None)
        )
        
        away_team_id = (
            detailed_match.get("away_team_id") or 
            detailed_match.get("awayTeamId") or
            (detailed_match.get("away_team", {}).get("id") if isinstance(detailed_match.get("away_team"), dict) else None)
        )
        away_team_name = (
            detailed_match.get("away_team_name") or 
            detailed_match.get("awayTeamName") or
            (detailed_match.get("away_team", {}).get("name") if isinstance(detailed_match.get("away_team"), dict) else None)
        )
        
        # If team names are not available, fetch them from team API by passing uuid parameter
        if (not home_team_name and home_team_id) or (not away_team_name and away_team_id):
            try:
                if sport_lower == "basketball":
                    team_endpoint = "basketball/team/list"
                elif sport_lower == "american_football":
                    team_endpoint = "american_football/team/list"
                elif sport_lower == "cricket":
                    team_endpoint = "cricket/team/list"
                else:
                    team_endpoint = f"{sport_lower}/team/list"
                
                # Fetch home team if needed
                if not home_team_name and home_team_id:
                    try:
                        team_data = await fetch_from_sports_api(team_endpoint, extra_params={"uuid": str(home_team_id)})
                        if isinstance(team_data, dict):
                            teams = team_data.get("results", team_data.get("teams", team_data.get("data", [])))
                        elif isinstance(team_data, list):
                            teams = team_data
                        else:
                            teams = []
                        
                        if teams and len(teams) > 0:
                            team = teams[0] if isinstance(teams, list) else teams
                            if isinstance(team, dict):
                                home_team_name = (
                                    team.get("name") or 
                                    team.get("team_name") or 
                                    team.get("teamName")
                                )
                    except Exception as e:
                        logger.warning(f"Error fetching home team {home_team_id}: {str(e)}")
                
                # Fetch away team if needed
                if not away_team_name and away_team_id:
                    try:
                        team_data = await fetch_from_sports_api(team_endpoint, extra_params={"uuid": str(away_team_id)})
                        if isinstance(team_data, dict):
                            teams = team_data.get("results", team_data.get("teams", team_data.get("data", [])))
                        elif isinstance(team_data, list):
                            teams = team_data
                        else:
                            teams = []
                        
                        if teams and len(teams) > 0:
                            team = teams[0] if isinstance(teams, list) else teams
                            if isinstance(team, dict):
                                away_team_name = (
                                    team.get("name") or 
                                    team.get("team_name") or 
                                    team.get("teamName")
                                )
                    except Exception as e:
                        logger.warning(f"Error fetching away team {away_team_id}: {str(e)}")
            except Exception as e:
                logger.warning(f"Could not fetch team details for uuid case: {str(e)}")
        
        match_time = (
            detailed_match.get("match_time") or 
            detailed_match.get("matchTime") or 
            detailed_match.get("start_time") or
            detailed_match.get("startTime") or
            detailed_match.get("time")
        )
        
        match_date = (
            detailed_match.get("match_date") or 
            detailed_match.get("matchDate") or 
            detailed_match.get("date")
        )
        
        # Format match_time if it's a timestamp
        formatted_time = None
        formatted_date = None
        if match_time:
            try:
                match_time_int = int(match_time)
                match_datetime = datetime.fromtimestamp(match_time_int)
                formatted_time = match_datetime.strftime("%H:%M:%S")
                formatted_date = match_datetime.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                formatted_time = str(match_time)
                formatted_date = match_date if match_date else None
        
        return {
            "competition_id": competition_id_str,
            "competition_name": competition_name,
            "competition_short_name": competition_short_name,
            "sport": sport_lower,
            "match_id": uuid_str,
            "home_team": {
                "id": home_team_id,
                "name": home_team_name
            },
            "away_team": {
                "id": away_team_id,
                "name": away_team_name
            },
            "match_time": formatted_time or match_time,
            "match_date": formatted_date or match_date,
            "match_datetime": match_time
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting match details by uuid: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get match details: {str(e)}")



@router.get("/team/{sport_name}/details")
async def get_team_player_details(
    sport_name: str,
    uuid: str = Query(..., description="Team UUID (home_team_id or away_team_id) to get details for")
):
    """
    Get team/player details by UUID (home_team_id or away_team_id)
    
    This endpoint fetches detailed information about a team or players using the team/list API
    with the uuid parameter. The UUID can be either a home_team_id or away_team_id.
    
    **Parameters:**
    - `sport_name`: Sport type (basketball, american_football, cricket, etc.)
    - `uuid`: Required. Team UUID (home_team_id or away_team_id) to get details for
    
    **Returns:**
    - Team details including: team_id, team_name, team_short_name, team_logo, etc.
    - Player information if available in the team data
    
    **Example:**
    - `/api/v1/sports/team/basketball/details?uuid=dn1m17tp9j8xmoe`
    - `/api/v1/sports/team/cricket/details?uuid=abc123xyz`
    
    **Response Format:**
    ```json
    {
        "sport": "basketball",
        "uuid": "dn1m17tp9j8xmoe",
        "team": {
            "team_id": "12345",
            "uuid": "dn1m17tp9j8xmoe",
            "team_name": "Los Angeles Lakers",
            "team_short_name": "LAL",
            "team_logo": "https://example.com/logo.png",
            ...
        }
    }
    ```
    """
    try:
        sport_lower = sport_name.lower()
        
        # Determine endpoint based on sport
        # For basketball, use squad/list endpoint to get player details
        fallback_endpoints: list[str] = []

        if sport_lower == "basketball":
            endpoint = "basketball/team/squad/list"
            fallback_endpoints = ["basketball/team/list"]
        elif sport_lower == "american_football":
            endpoint = "american_football/team/squad/list"
            fallback_endpoints = ["american_football/team/list"]
        elif sport_lower == "cricket":
            endpoint = "cricket/team/list"
        else:
            # Try generic endpoint for other sports
            endpoint = f"{sport_lower}/team/list"
        
        logger.info(f"Fetching team/player details for {sport_lower}, uuid: {uuid}")
        
        # Fetch team details using uuid parameter
        async def fetch_team_details(target_endpoint: str):
            logger.debug(f"Attempting to fetch team details from endpoint={target_endpoint} uuid={uuid}")
            return await fetch_from_sports_api(target_endpoint, extra_params={"uuid": uuid})

        team_data = await fetch_team_details(endpoint)

        def extract_team_payload(payload):
            squads = None
            teams_payload = []

            if isinstance(payload, dict):
                results = payload.get("results")
                teams_section = payload.get("teams")
                data_section = payload.get("data")

                if isinstance(results, list) and results:
                    first_result = results[0]
                    if isinstance(first_result, dict) and "squad" in first_result:
                        squads = first_result.get("squad", [])
                        teams_payload = [first_result]
                    else:
                        teams_payload = results
                elif isinstance(teams_section, list):
                    teams_payload = teams_section
                elif isinstance(data_section, list):
                    teams_payload = data_section
                elif isinstance(data_section, dict):
                    teams_payload = [data_section]
            elif isinstance(payload, list):
                teams_payload = payload

            return teams_payload, squads

        teams, squad_data = extract_team_payload(team_data)

        # Fallback to alternate endpoints if no records returned
        if (not teams or len(teams) == 0) and fallback_endpoints:
            for alt_endpoint in fallback_endpoints:
                logger.info(f"No data from {endpoint}. Trying fallback endpoint {alt_endpoint}")
                alt_data = await fetch_team_details(alt_endpoint)
                teams, squad_data = extract_team_payload(alt_data)
                if teams and len(teams) > 0:
                    endpoint = alt_endpoint
                    break
        
        if not teams or len(teams) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Team/player not found with uuid: {uuid} for sport: {sport_name}"
            )
        
        # Get the first team (should be the matching one when uuid is provided)
        team = teams[0] if isinstance(teams, list) else teams
        
        if not isinstance(team, dict):
            raise HTTPException(
                status_code=404,
                detail=f"Team/player data not found with uuid: {uuid} for sport: {sport_name}"
            )
        
        # Extract team details
        team_id = (
            team.get("id") or 
            team.get("team_id") or 
            team.get("teamId") or
            team.get("uuid") or
            uuid
        )
        
        team_name = (
            team.get("name") or 
            team.get("team_name") or 
            team.get("teamName") or
            team.get("team_name_full")
        )
        
        team_short_name = (
            team.get("short_name") or 
            team.get("shortName") or
            team.get("team_short_name") or
            team.get("abbreviation")
        )
        
        team_logo = (
            team.get("logo") or 
            team.get("team_logo") or
            team.get("teamLogo") or
            team.get("image_url") or
            team.get("imageUrl")
        )
        
        # Extract additional team information
        team_details = {
            "team_id": str(team_id) if team_id else uuid,
            "uuid": uuid,
            "team_name": team_name,
            "team_short_name": team_short_name,
            "team_logo": team_logo,
            "sport": sport_lower,
            # Include all other team fields
            "country": team.get("country"),
            "country_code": team.get("country_code") or team.get("countryCode"),
            "competition_id": team.get("competition_id") or team.get("competitionId"),
            "competition_name": team.get("competition_name") or team.get("competitionName"),
            "founded": team.get("founded"),
            "venue": team.get("venue") or team.get("stadium"),
            "website": team.get("website") or team.get("url"),
            # Players information if available - use squad_data if from squad/list endpoint
            "players": squad_data if squad_data is not None else (team.get("players") or team.get("squad") or team.get("lineup")),
            "squad": squad_data if squad_data is not None else team.get("squad"),
            "squad_count": len(squad_data) if squad_data is not None and isinstance(squad_data, list) else (len(team.get("squad", [])) if isinstance(team.get("squad"), list) else 0),
            # Include all other fields from the API response
            "raw_data": team  # Include full response for flexibility
        }

        # Enrich american football players with name/logo from player list
        if sport_lower == "american_football":
            players_list: list = []
            if isinstance(team_details.get("players"), list):
                players_list = team_details["players"]
            elif isinstance(team_details.get("players"), dict):
                players_list = [team_details["players"]]

            player_cache: Dict[str, Optional[Dict]] = {}

            for player in players_list:
                if not isinstance(player, dict):
                    continue

                identifier_candidates = [
                    player.get("uuid"),
                    player.get("player_uuid"),
                    player.get("playerUuid"),
                    player.get("player_id"),
                    player.get("playerId"),
                    player.get("id")
                ]

                player_identifier = next(
                    (str(candidate) for candidate in identifier_candidates if candidate),
                    None
                )

                if not player_identifier:
                    continue

                if player_identifier not in player_cache:
                    try:
                        player_response = await fetch_from_sports_api(
                            "american_football/player/list",
                            extra_params={"uuid": player_identifier}
                        )

                        if isinstance(player_response, dict):
                            payload = (
                                player_response.get("results")
                                or player_response.get("players")
                                or player_response.get("data")
                                or player_response.get("squad")
                                or []
                            )
                        elif isinstance(player_response, list):
                            payload = player_response
                        else:
                            payload = []

                        matched_profile = None
                        for profile in payload:
                            if not isinstance(profile, dict):
                                continue

                            profile_ids = [
                                profile.get("uuid"),
                                profile.get("player_uuid"),
                                profile.get("playerUuid"),
                                profile.get("id"),
                                profile.get("player_id"),
                                profile.get("playerId")
                            ]

                            if any(str(pid) == player_identifier for pid in profile_ids if pid):
                                matched_profile = profile
                                break

                        player_cache[player_identifier] = matched_profile
                    except HTTPException:
                        raise
                    except Exception as player_fetch_error:
                        logger.warning(
                            f"Failed to enrich american football player {player_identifier}: {player_fetch_error}"
                        )
                        player_cache[player_identifier] = None

                matched_player = player_cache.get(player_identifier)

                if matched_player:
                    player_name = (
                        matched_player.get("name")
                        or matched_player.get("player_name")
                        or matched_player.get("fullname")
                        or matched_player.get("full_name")
                        or matched_player.get("short_name")
                    )
                    player_logo = (
                        matched_player.get("logo")
                        or matched_player.get("image_url")
                        or matched_player.get("imageUrl")
                        or matched_player.get("player_image")
                        or matched_player.get("playerImage")
                        or matched_player.get("photo")
                        or matched_player.get("avatar")
                    )

                    player["name"] = player_name
                    player["player_name"] = player_name
                    player["logo"] = player_logo
                    player["player_logo"] = player_logo
                    player["player_profile"] = matched_player
        
        return {
            "status": "success",
            "message": f"Team/player details retrieved successfully for {sport_name}",
            "sport": sport_lower,
            "uuid": uuid,
            "data": team_details
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting team/player details: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get team/player details: {str(e)}"
        )



@router.get("/leagues")
async def get_leagues_by_sport(
    sport: str = Query(..., description="Sport name (basketball, american_football, cricket, etc.)"),
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    limit: int = Query(1000, ge=1, le=1000, description="Number of items per page (max 100)")
):
    """
    Get leagues/competitions by sport with automatic multi-page fetching
    """
    try:
        sport_lower = sport.lower()
        supported_sports = ["basketball", "american_football", "cricket", "football", "tennis"]

        if sport_lower not in supported_sports:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported sport. Supported: {', '.join(supported_sports)}"
            )

        # 🟢 NEW LOGIC: handle multi-page competition fetching for all sports
        async def fetch_all_competitions(base_endpoint: str):
            """
            Fetch all pages from TheSports competition/list endpoint.
            """
            all_competitions = []
            current_page = 1

            while True:
                extra_params = {"page": current_page}
                data = await fetch_from_sports_api(base_endpoint, extra_params)

                # Handle data from multiple response formats
                if isinstance(data, dict):
                    results = data.get("results") or data.get("competitions") or data.get("data") or []
                elif isinstance(data, list):
                    results = data
                else:
                    results = []

                if not results:
                    break  # Stop if no more results

                all_competitions.extend(results)

                # Stop if less than 1000 results (last page)
                if len(results) < 1000:
                    break

                current_page += 1

            return all_competitions

        # 🟠 FETCH COMPETITIONS BASED ON SPORT
        if sport_lower == "american_football":
            endpoint = "american_football/unique_tournament/list"
        else:
            endpoint = f"{sport_lower}/competition/list"

        logger.info(f"Fetching all competitions for {sport_lower} from {endpoint}")
        competitions = await fetch_all_competitions(endpoint)

        if not competitions:
            raise HTTPException(status_code=404, detail=f"No competitions found for {sport_lower}")

        logger.info(f"✅ Total competitions fetched: {len(competitions)}")

        # 🟢 Standardize output format
        competitions_list = []
        for comp in competitions:
            if not isinstance(comp, dict):
                continue
            comp_id = str(comp.get("id") or comp.get("competition_id") or comp.get("competitionId") or "")
            if not comp_id:
                continue
            competitions_list.append({
                "competition_id": comp_id,
                "competition_name": (
                    comp.get("name") or comp.get("competition_name") or comp.get("competitionName") or ""
                ),
                "competition_short_name": (
                    comp.get("short_name") or comp.get("shortName") or comp.get("competition_short_name") or ""
                )
            })

        # 🧮 Apply pagination on combined data
        total_competitions = len(competitions_list)
        total_pages = (total_competitions + limit - 1) // limit if total_competitions > 0 else 0
        skip = (page - 1) * limit
        paginated_competitions = competitions_list[skip:skip + limit]

        return {
            "sport": sport_lower,
            "total_competitions": total_competitions,
            "competitions": paginated_competitions,
            "pagination": {
                "total_items": total_competitions,
                "total_pages": total_pages,
                "current_page": page,
                "page_size": limit,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting leagues by sport: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get leagues: {str(e)}")



async def fetch_all_pages(endpoint: str, max_pages: int = 10):
    """
    Fetch all paginated data from TheSports API.
    Stops when a page returns <1000 results or when max_pages reached.
    """
    all_data = []
    page = 1

    while page <= max_pages:
        try:
            logger.info(f"Fetching page {page} from {endpoint}")
            data = await fetch_from_sports_api(endpoint, extra_params={"page": page})

            if isinstance(data, dict):
                page_data = (
                    data.get("data")
                    or data.get("results")
                    or data.get("matches")
                    or []
                )
            elif isinstance(data, list):
                page_data = data
            else:
                page_data = []

            if not page_data:
                logger.info(f"No data found at page {page}, stopping.")
                break

            all_data.extend(page_data)

            # Stop if this page has fewer than 1000 (API default)
            if len(page_data) < 1000:
                break

            page += 1
        except Exception as e:
            logger.warning(f"Error fetching page {page}: {e}")
            break

    logger.info(f"Total records fetched from all pages: {len(all_data)}")
    return all_data



# --------------------------------
# Helper: Fetch team details by UUID
# --------------------------------
async def fetch_team_name(team_id: str, sport: str) -> str:
    """Fetch team name by team UUID from TheSports API."""
    try:
        endpoint = f"{sport}/team/list"
        params = {"uuid": team_id}
        response = await fetch_from_sports_api(endpoint, extra_params=params)
        print(f"Response: {response}")
        if isinstance(response, dict) and "results" in response:
            team_data = response["results"]
            if isinstance(team_data, list) and team_data:
                return team_data[0].get("name", "Unknown Team")
        return "Unknown Team"
    except Exception as e:
        logger.warning(f"Failed to fetch team {team_id}: {e}")
        return "Unknown Team"


async def fetch_team_logo(team_id: str, sport: str) -> Optional[str]:
    """Fetch team logo by team UUID from TheSports API."""
    try:
        endpoint = f"{sport}/team/list"
        params = {"uuid": team_id}
        response = await fetch_from_sports_api(endpoint, extra_params=params)
        if isinstance(response, dict) and "results" in response:
            team_data = response["results"]
            if isinstance(team_data, list) and team_data:
                team = team_data[0]
                # Try different possible keys for logo
                logo = team.get("logo") or team.get("team_logo") or team.get("teamLogo")
                return logo if logo else None
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch team logo for {team_id}: {e}")
        return None


# from fastapi import APIRouter, Query, HTTPException
# import httpx

# router = APIRouter()

THESPORTS_API_BASE = "https://api.thesports.com/v1/basketball/match/recent/list"
API_USER = "mvpsports"
API_SECRET = "55df235bf1c0a03e4236c5b413b38c1a"

async def fetch_page(page: int = 1):
    """Fetch a single page from TheSports API"""
    async with httpx.AsyncClient() as client:
        params = {
            "user": API_USER,
            "secret": API_SECRET,
            "page": page
        }
        response = await client.get(THESPORTS_API_BASE, params=params)
        response.raise_for_status()
        data = response.json()
        return data

async def fetch_page(page: int):
    """Fetch a single page from TheSports API"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {
            "user": API_USER,
            "secret": API_SECRET,
            "page": page
        }
        resp = await client.get(THESPORTS_API_BASE, params=params)
        resp.raise_for_status()
        return resp.json()


@router.get("/competition/matchesss")
async def get_matches_by_competition(
    competition_id: str = Query(..., description="Competition ID (e.g. z8yomovt7dq0j6l)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(1000, ge=1, le=1000)
):
    """
    ✅ Fetch matches from TheSports API using match/list endpoint (not recent/list).
    Returns all matches for a given competition_id, even if old.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "user": API_USER,
                "secret": API_SECRET,
                "competition_id": competition_id,
                "page": page,
                "limit": limit
            }
            response = await client.get(THESPORTS_API_BASE, params=params)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        if not results:
            return {
                "competition_id": competition_id,
                "total_matches": 0,
                "matches": []
            }

        matches = [
            {
                "match_id": m["id"],
                "home_team_id": m["home_team_id"],
                "away_team_id": m["away_team_id"],
                "competition_id": m["competition_id"],
                "match_time": m.get("match_time"),
                "status_id": m.get("status_id")
            }
            for m in results
        ]

        return {
            "competition_id": competition_id,
            "total_matches": len(matches),
            "matches": matches
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/basketball/recent/max-pages")
async def get_basketball_recent_max_pages(max_pages: int = 50):
    """
    Find the maximum number of pages available in TheSports basketball recent matches API.
    Stops when a page has <1000 results or when max_pages reached.
    """
    endpoint = "basketball/match/recent/list"
    page = 1
    total_records = 0

    try:
        while page <= max_pages:
            logger.info(f"🔍 Checking page {page} for {endpoint}")
            data = await fetch_from_sports_api(endpoint, extra_params={"page": page})

            # Normalize the data
            if isinstance(data, dict):
                page_data = (
                    data.get("data")
                    or data.get("results")
                    or data.get("matches")
                    or []
                )
            elif isinstance(data, list):
                page_data = data
            else:
                page_data = []

            logger.info(f"📄 Page {page} returned {len(page_data)} items")

            total_records += len(page_data)

            # # Stop when this page has < 1000 results (API default)
            # if len(page_data) < 1000:
            #     logger.info(f"✅ Found last page at {page}")
            #     return {
            #         "max_page": page,
            #         "total_records": total_records,
            #         "last_page_count": len(page_data),
            #         "endpoint": endpoint
            #     }

            page += 1

        return {
            "max_page": max_pages,
            "total_records": total_records,
            "message": "Reached max_pages limit before finding the last page."
        }

    except Exception as e:
        logger.error(f"❌ Error while checking max pages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/competitions/{competition_id}/matches")
async def get_matches_by_competition(
    competition_id: str,
    sport: str = Query(..., description="Sport name, e.g., basketball"),
    page: int = Query(1, ge=1, description="Frontend page number"),
    limit: int = Query(1000, ge=1, le=1000, description="Frontend page size"),
    sort_order: Optional[str] = Query("desc", description="Sort by match start time (asc/desc)"),
):
    """
    Get all basketball matches for a specific competition (league).
    Fetches all pages dynamically and filters by competition_id.
    """
    if sport == "basketball":
        endpoint = "basketball/match/recent/list"
    elif sport == "american_football":
        endpoint = "american_football/match/list"
    else:
        raise HTTPException(status_code=400, detail="Invalid sport")
    
    print(f"Endpoint: {endpoint}")
    # endpoint = "basketball/match/recent/list"
    max_pages = 60  # Adjust if needed

    all_matches = []
    for p in range(1, max_pages + 1):
        logger.info(f"Fetching page {p} for {endpoint}")
        data = await fetch_from_sports_api(endpoint, extra_params={"page": p})

        if isinstance(data, dict):
            page_data = (
                data.get("data")
                or data.get("results")
                or data.get("matches")
                or []
            )
        elif isinstance(data, list):
            page_data = data
        else:
            page_data = []

        if not page_data:
            break

        all_matches.extend(page_data)

        # if len(page_data) < 1000:
        #     break

    if not all_matches:
        logger.warning(
            "Matches are not available for this league at this time.",
            extra={
                "competition_id": competition_id,
                "sport": sport,
                "endpoint": endpoint,
            },
        )
        return create_response(
            404,
            "error",
            "Matches are not available for this league at this time.",
            {
                "competition_id": competition_id,
                "sport": sport,
                "matches": [],
            },
        )

    # ✅ Filter by competition ID
    # filtered = [m for m in all_matches if m.get("competition_id") == competition_id]
    if sport == "american_football":
        filtered = [m for m in all_matches if m.get("unique_tournament_id") == competition_id]
    else:
        filtered = [m for m in all_matches if m.get("competition_id") == competition_id]
    if not filtered:
        logger.warning(
            "Matches are not available for this league at this time.",
            extra={
                "competition_id": competition_id,
                "sport": sport,
                "total_matches": len(all_matches),
            },
        )
        return create_response(
            404,
            "error",
            "Matches are not available for this league at this time.",
            {
                "competition_id": competition_id,
                "sport": sport,
                "matches": [],
            },
        )

    # ✅ Sort matches by match_time
    filtered.sort(key=lambda x: x.get("match_time", 0), reverse=("desc" in sort_order.lower()))

    # ✅ Collect all unique team IDs
    team_ids = set()
    for m in filtered:
        if m.get("home_team_id"):
            team_ids.add(m["home_team_id"])
        if m.get("away_team_id"):
            team_ids.add(m["away_team_id"])

     # ✅ Fetch all team names concurrently using your helper
    team_map: Dict[str, str] = {}
    if sport == "american_football":
        name_tasks = [fetch_team_name(team_id, "american_football") for team_id in team_ids]
    else:
        name_tasks = [fetch_team_name(team_id, "basketball") for team_id in team_ids]
    name_results = await asyncio.gather(*name_tasks, return_exceptions=True)

    for team_id, result in zip(team_ids, name_results):
        if isinstance(result, str):
            team_map[team_id] = result
        else:
            team_map[team_id] = "Unknown Team"

    # ✅ Fetch all team logos concurrently
    logo_map: Dict[str, Optional[str]] = {}
    if sport == "american_football":
        logo_tasks = [fetch_team_logo(team_id, "american_football") for team_id in team_ids]
    else:
        logo_tasks = [fetch_team_logo(team_id, "basketball") for team_id in team_ids]
    logo_results = await asyncio.gather(*logo_tasks, return_exceptions=True)

    for team_id, result in zip(team_ids, logo_results):
        if isinstance(result, str):
            logo_map[team_id] = result
        else:
            logo_map[team_id] = None

    # ✅ Build final enriched list
    enriched_matches = []
    for match in filtered:
        enriched_matches.append({
            "match_id": match.get("id"),
            "competition_id": match.get("competition_id"),
            "home_team_id": match.get("home_team_id"),
            "home_team_name": team_map.get(match.get("home_team_id"), "Unknown"),
            "home_logo": logo_map.get(match.get("home_team_id")),
            "away_team_id": match.get("away_team_id"),
            "away_team_name": team_map.get(match.get("away_team_id"), "Unknown"),
            "away_logo": logo_map.get(match.get("away_team_id")),
            "match_time": match.get("match_time"),
            # "status": match.get("status"),
        })

    # ✅ Pagination
    total = len(enriched_matches)
    start = (page - 1) * limit
    end = start + limit
    paginated = enriched_matches[start:end]

    # ✅ Collect participating team names (for reference)
    participating_teams = list({
        team_map.get(m.get("home_team_id"), "Unknown")
        for m in filtered
    } | {
        team_map.get(m.get("away_team_id"), "Unknown")
        for m in filtered
    })

    return {
        "competition_id": competition_id,
        "total_matches": total,
        "total_teams": len(participating_teams),
        "teams": participating_teams,
        "page": page,
        "limit": limit,
        "matches": paginated
    }
# --------------------------------
# Main Route
# --------------------------------
# @router.get("/competitions/{competition_id}/matches")
# async def get_matches_by_competition(
#     competition_id: str,
#     sport: str = Query(..., description="Sport name, e.g., basketball"),
#     page: int = Query(1, ge=1, description="Frontend page number"),
#     limit: int = Query(1000, ge=1, le=1000, description="Frontend page size"),
#     sort_order: Optional[str] = Query("desc", description="Sort by match start time (asc/desc)"),
# ):
#     """
#     Get all matches for a specific competition (league).
#     Fetches all pages from TheSports API dynamically without DB storage.
#     Then fetches team names by UUIDs for each match.
#     """
#     if sport == "basketball":
#         endpoint = "basketball/match/recent/list"
#     elif sport == "american_football":
#         endpoint = "american_football/match/list"
#     else:
#         raise HTTPException(status_code=400, detail="Invalid sport")
    
#     print(f"Endpoint: {endpoint}")

#     # ✅ Fetch all pages of matches
#     all_matches = await fetch_all_pages(endpoint)

#     if not all_matches:
#         raise HTTPException(status_code=404, detail="No matches found")
#     if sport == "american_football":
#         filtered = [m for m in all_matches if m.get("unique_tournament_id") == competition_id]
#     else:
#         filtered = [m for m in all_matches if m.get("competition_id") == competition_id]
#     # ✅ Filter by competition ID
#     # filtered = [m for m in all_matches if m.get("competition_id") == competition_id]
#     if not filtered:
#         raise HTTPException(status_code=404, detail=f"No matches found for competition {competition_id}")

#     # ✅ Sort matches
#     if "desc" in sort_order.lower():
#         filtered.sort(key=lambda x: x.get("match_time", 0), reverse=True)
#     else:
#         filtered.sort(key=lambda x: x.get("match_time", 0))

#     # ✅ Collect all unique team IDs
#     team_ids = set()
#     for m in filtered:
#         if m.get("home_team_id"):
#             team_ids.add(m["home_team_id"])
#         if m.get("away_team_id"):
#             team_ids.add(m["away_team_id"])
#     print(f"Team IDs: {team_ids}")
#     # ✅ Fetch all team names concurrently
#     team_map: Dict[str, str] = {}
#     tasks = [fetch_team_name(team_id, sport) for team_id in team_ids]
#     results = await asyncio.gather(*tasks, return_exceptions=True)

#     for team_id, name in zip(team_ids, results):
#         team_map[team_id] = name if isinstance(name, str) else "Unknown Team"

#     # ✅ Build final match data
#     enriched_matches = []
#     for match in filtered:
#         home_id = match.get("home_team_id")
#         away_id = match.get("away_team_id")
#         match_id = match.get("id")
#         # if sport == "american_football":
#         #     match_id = match.get("unique_tournament_id")
#         # else:
#         #     match_id = match.get("match_id")
#         enriched_matches.append({
#             "match_id": match_id,
#             "home_team_id": home_id,
#             "home_team_name": team_map.get(home_id, "Unknown Home"),
#             "away_team_id": away_id,
#             "away_team_name": team_map.get(away_id, "Unknown Away"),
#             "match_time": match.get("match_time")
#         })

#     # ✅ Pagination for frontend
#     total = len(enriched_matches)
#     start = (page - 1) * limit
#     end = start + limit
#     paginated = enriched_matches[start:end]

#     return {
#         "competition_id": competition_id,
#         "total_matches": total,
#         "page": page,
#         "limit": limit,
#         "matches": paginated
#     }


# @router.get("/competitions/{competition_id}/matchestest")
# async def get_matches_by_competition(
#     competition_id: str,
#     sport: str = Query(..., description="Sport name, e.g., basketball, american_football"),
#     page: int = Query(1, ge=1, description="Frontend page number"),
#     limit: int = Query(1000, ge=1, le=1000, description="Frontend page size"),
#     sort_order: Optional[str] = Query("desc", description="Sort by match start time (asc/desc)")
# ):
#     """
#     Fetch all matches for a given competition ID.
#     Dynamically loads all pages from TheSports API and filters matches.
#     """
#     try:
#         sport_lower = sport.lower()
#         supported_sports = ["basketball", "american_football", "cricket", "football", "tennis"]
#         if sport_lower not in supported_sports:
#             raise HTTPException(status_code=400, detail=f"Unsupported sport: {sport_lower}")

#         # 🟢 Select the correct endpoint for the given sport
#         if sport_lower == "basketball":
#             endpoint = "basketball/match/recent/list"
#         elif sport_lower == "american_football":
#             endpoint = "american_football/match/list"
#         else:
#             endpoint = f"{sport_lower}/match/list"

#         logger.info(f"Fetching matches from {endpoint} for competition {competition_id}")

#         # 🧩 Fetch all pages of matches (using same logic as in /leagues)
#         async def fetch_all_pages(endpoint: str, max_pages: int = 10):
#             all_data = []
#             page = 1
#             while page <= max_pages:
#                 data = await fetch_from_sports_api(endpoint, extra_params={"page": page})
#                 if isinstance(data, dict):
#                     results = data.get("results") or data.get("data") or []
#                 elif isinstance(data, list):
#                     results = data
#                 else:
#                     results = []

#                 if not results:
#                     break

#                 all_data.extend(results)

#                 # Stop when last page reached (<1000 items)
#                 if len(results) < 1000:
#                     break
#                 page += 1
#             return all_data

#         all_matches = await fetch_all_pages(endpoint)

#         if not all_matches:
#             raise HTTPException(status_code=404, detail=f"No matches found for sport {sport_lower}")

#         # 🧠 Filter by competition_id or unique_tournament_id
#         filtered = []
#         for match in all_matches:
#             comp_id = (
#                 match.get("competition_id")
#                 or match.get("unique_tournament_id")
#                 or match.get("tournament_id")
#             )
#             if comp_id == competition_id:
#                 filtered.append(match)

#         if not filtered:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"No matches found for competition ID {competition_id}"
#             )

#         # 🕒 Sort matches by match_time
#         filtered.sort(key=lambda x: x.get("match_time", 0), reverse=(sort_order.lower() == "desc"))

#         # 🧾 Collect all unique team IDs
#         team_ids = {
#             m.get("home_team_id") for m in filtered if m.get("home_team_id")
#         } | {
#             m.get("away_team_id") for m in filtered if m.get("away_team_id")
#         }

#         logger.info(f"Total team IDs collected: {len(team_ids)}")

#         # ⚡ Fetch team names concurrently
#         team_map = {}
#         tasks = [fetch_team_name(team_id, sport_lower) for team_id in team_ids]
#         results = await asyncio.gather(*tasks, return_exceptions=True)
#         for team_id, name in zip(team_ids, results):
#             team_map[team_id] = name if isinstance(name, str) else "Unknown Team"

#         # 🧩 Prepare enriched match data
#         enriched = []
#         for m in filtered:
#             home_id = m.get("home_team_id")
#             away_id = m.get("away_team_id")
#             enriched.append({
#                 "match_id": m.get("id"),
#                 "competition_id": competition_id,
#                 "home_team_id": home_id,
#                 "home_team_name": team_map.get(home_id, "Unknown Home"),
#                 "away_team_id": away_id,
#                 "away_team_name": team_map.get(away_id, "Unknown Away"),
#                 "match_time": m.get("match_time"),
#                 "status_id": m.get("status_id"),
#                 "period_count": m.get("period_count"),
#             })

#         # 🧮 Apply pagination for frontend
#         total = len(enriched)
#         start = (page - 1) * limit
#         end = start + limit
#         paginated = enriched[start:end]

#         return {
#             "competition_id": competition_id,
#             "sport": sport_lower,
#             "total_matches": total,
#             "page": page,
#             "limit": limit,
#             "matches": paginated,
#         }

#     except HTTPException as e:
#         raise e
#     except Exception as e:
#         logger.error(f"Error fetching matches by competition: {e}")
#         raise HTTPException(status_code=500, detail=f"Failed to get matches: {str(e)}")


import os
import requests
@router.get("/player-stats")
async def get_live_player_stats(match_id: str = Query(..., description="Match ID to get live stats")):
    """Fetch live player stats and emit updates via Socket.IO"""
    try:
        params = {
            "user": os.getenv("SPORTS_USER_TOKEN"),
            "secret": os.getenv("SPORTS_SECRET_TOKEN"),
            "id": match_id
        }
        API_URL = "https://api.thesports.com/v1/basketball/match/lineup_live"

        response = requests.get(API_URL, params=params)
        data = response.json()

        # Emit to all connected clients
        await socket_manager.sio.emit("live_player_stats", data)

        return {"message": "Live data emitted successfully", "data": data}

    except Exception as e:
        return {"error": str(e)}
import httpx, os

@router.get("/players")
async def get_players(uuid: str):
    url = f"https://api.thesports.com/v1/basketball/player/list"
    params = {
        "uuid": uuid,
        "user": "mvpsports",
        "secret": "55df235bf1c0a03e4236c5b413b38c1a"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
    return resp.json()