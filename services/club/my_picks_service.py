"""
My Picks Service - Handle retrieval of picks/bets based on user role and club memberships
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict
from bson import ObjectId
from fastapi import HTTPException, status
import logging
import math

from core.database.collections import get_collections
from .my_clubs_service import MyClubsService

logger = logging.getLogger(__name__)


class MyPicksService:
    """Service for managing user's picks based on their role and club memberships"""
    
    def __init__(self):
        self.collections = get_collections()
        self.picks_collection = self.collections.get_club_picks_collection()
        self.clubs_collection = self.collections.get_clubs_collection()
        self.memberships_collection = self.collections.get_club_memberships_collection()
        self.users_collection = self.collections.get_users_collection()
        self.my_clubs_service = MyClubsService()
    
    async def get_my_picks(
        self,
        user_id: str,
        status_filter: Optional[str] = None,
        pick_type_filter: Optional[str] = None,
        result_filter: Optional[str] = None,
        sport_league_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict:
        """
        Get picks for a user based on their role and club memberships
        Optimized with parallel processing for better performance
        
        Args:
            user_id: User ID
            status_filter: Optional status filter (pending/completed)
            pick_type_filter: Optional pick type filter (case-insensitive)
            result_filter: Optional result filter (pending/win/loss)
            sport_league_filter: Optional sport or league filter (searches both fields, case-insensitive)
            date_from: Optional start date filter (datetime)
            date_to: Optional end date filter (datetime)
            search: Optional search term (searches pick_type, club_name, league)
            page: Page number
            limit: Items per page
            
        Returns:
            Dict containing picks list and metadata
        """
        try:
            import time
            service_start_time = time.time()
            logger.info(f"🔍 Service: Starting get_my_picks for user {user_id}")
            
            # Validate user_id format
            validation_start = time.time()
            if not ObjectId.is_valid(user_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid user ID format"
                )
            
            # Get user details
            user_query_start = time.time()
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            user_query_time = time.time() - user_query_start
            logger.info(f"⏱️ User query took {user_query_time:.3f}s")
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            user_role = user.get("role", "Member")
            
            # Validate user_role
            if not user_role or user_role.lower() not in ["captain", "moderator", "member"]:
                logger.warning(f"Invalid user role '{user_role}' for user {user_id}, defaulting to 'Member'")
                user_role = "Member"
            
            # Get user's clubs based on their role
            clubs_start = time.time()
            user_clubs = await self._get_user_clubs(user_id, user_role)
            clubs_time = time.time() - clubs_start
            logger.info(f"⏱️ Getting user clubs took {clubs_time:.3f}s - Found {len(user_clubs)} clubs")
            
            if not user_clubs:
                return {
                    "picks": [],
                    "total": 0,
                    "page": page,
                    "limit": limit,
                    "total_pages": 0,
                    "user_role": user_role,
                    "clubs_count": 0
                }
            
            # OPTIMIZATION: Get picks and count in single aggregation query
            picks_and_count_start = time.time()
            picks_result = await self._get_picks_with_count_optimized(
                user_clubs, 
                user_id,
                user_role,
                status_filter, 
                pick_type_filter,
                result_filter,
                sport_league_filter,
                date_from,
                date_to,
                search,
                page,
                limit
            )
            picks_and_count_time = time.time() - picks_and_count_start
            picks = picks_result["picks"]
            total_count = picks_result["total"]
            result_page = picks_result.get("page", page)
            logger.info(f"⏱️ OPTIMIZED: Getting picks + count took {picks_and_count_time:.3f}s - Found {len(picks)} picks, Total: {total_count}")
            
            total_pages = math.ceil(total_count / limit) if limit > 0 else 0
            
            total_service_time = time.time() - service_start_time
            logger.info(f"✅ Service completed in {total_service_time:.3f}s")
            
            return {
                "picks": picks,
                "total": total_count,
                "page": result_page,
                "limit": limit,
                "total_pages": total_pages,
                "user_role": user_role,
                "clubs_count": len(user_clubs)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting my picks for user {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get picks: {str(e)}"
            )
    
    async def _get_user_clubs(self, user_id: str, user_role: str) -> List[Dict]:
        """
        Get clubs that the user has access to based on their role
        OPTIMIZED VERSION: Uses parallel queries instead of sequential queries
        
        Args:
            user_id: User ID
            user_role: User's role (Captain, Moderator, Member)
            
        Returns:
            List of club dictionaries with access information
        """
        import time
        import asyncio
        clubs_start = time.time()
        logger.info(f"🔍 Getting clubs for user {user_id} with role {user_role} (OPTIMIZED)")
        
        try:
            # OPTIMIZATION: Execute all queries in parallel instead of sequentially
            parallel_start = time.time()
            
            # Create all query tasks
            tasks = []
            
            # Task 1: Captain clubs
            captain_task = self.clubs_collection.find({
                "captain_id": user_id,
                "$or": [
                    {"status": "approved"},
                    {"is_active": True},
                    {"status": {"$exists": False}},
                    {"is_active": {"$exists": False}}
                ]
            }).to_list(length=None)
            tasks.append(("captain", captain_task))
            
            # Task 2: Moderator clubs (fixed query logic)
            moderator_task = self.clubs_collection.find({
                "$and": [
                    {
                        "$or": [
                            {"moderators.user_id": user_id, "moderators.status": "active"},
                            {"detailed_moderators.user_id": user_id, "detailed_moderators.status": "active"}
                        ]
                    },
                    {
                        "$or": [
                            {"status": "approved"},
                            {"is_active": True},
                            {"status": {"$exists": False}},
                            {"is_active": {"$exists": False}}
                        ]
                    }
                ]
            }).to_list(length=None)
            tasks.append(("moderator", moderator_task))
            
            # Task 3: Member clubs (from arrays) - fixed query logic
            member_task = self.clubs_collection.find({
                "$and": [
                    {
                        "$or": [
                            {"members.user_id": user_id},
                            {"paid_members.user_id": user_id}
                        ]
                    },
                    {
                        "$or": [
                            {"status": "approved"},
                            {"is_active": True},
                            {"status": {"$exists": False}},
                            {"is_active": {"$exists": False}}
                        ]
                    }
                ]
            }).to_list(length=None)
            tasks.append(("member", member_task))
            
            # Task 4: Memberships
            membership_task = self.memberships_collection.find({
                "user_id": user_id,
                "subscription_status": "active"
            }).to_list(length=None)
            tasks.append(("membership", membership_task))
            
            # Execute all queries in parallel
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)
            parallel_time = time.time() - parallel_start
            logger.info(f"⏱️ OPTIMIZED: Parallel queries took {parallel_time:.3f}s")
            
            # Process results
            captain_clubs = results[0] if not isinstance(results[0], Exception) else []
            moderator_clubs = results[1] if not isinstance(results[1], Exception) else []
            member_clubs = results[2] if not isinstance(results[2], Exception) else []
            memberships = results[3] if not isinstance(results[3], Exception) else []
            
            logger.info(f"📊 Query results: Captain={len(captain_clubs)}, Moderator={len(moderator_clubs)}, Member={len(member_clubs)}, Memberships={len(memberships)}")
            
            # Debug: Show which clubs are being returned
            if captain_clubs:
                captain_club_ids = [club.get("name_based_id") for club in captain_clubs]
                logger.info(f"🔍 Captain clubs: {captain_club_ids}")
            
            if moderator_clubs:
                moderator_club_ids = [club.get("name_based_id") for club in moderator_clubs]
                logger.info(f"🔍 Moderator clubs: {moderator_club_ids}")
            
            if member_clubs:
                member_club_ids = [club.get("name_based_id") for club in member_clubs]
                logger.info(f"🔍 Member clubs: {member_club_ids}")
            
            # Combine all clubs and determine roles efficiently
            all_clubs_dict = {}
            
            # Process captain clubs (highest priority)
            for club in captain_clubs:
                club_id = club.get("name_based_id")
                if club_id:
                    all_clubs_dict[club_id] = {
                        **club,
                        "user_role_in_club": "captain"
                    }
            
            # Process moderator clubs (second priority)
            for club in moderator_clubs:
                club_id = club.get("name_based_id")
                if club_id and club_id not in all_clubs_dict:
                    all_clubs_dict[club_id] = {
                        **club,
                        "user_role_in_club": "moderator"
                    }
            
            # Process member clubs (lowest priority)
            for club in member_clubs:
                club_id = club.get("name_based_id")
                if club_id and club_id not in all_clubs_dict:
                    all_clubs_dict[club_id] = {
                        **club,
                        "user_role_in_club": "member"
                    }
            
            # Process membership clubs
            if memberships:
                membership_club_ids = [ObjectId(m.get("club_id")) for m in memberships if m.get("club_id")]
                if membership_club_ids:
                    membership_clubs = await self.clubs_collection.find({
                        "_id": {"$in": membership_club_ids},
                        "name_based_id": {"$nin": list(all_clubs_dict.keys())},
                        "$or": [
                            {"status": "approved"},
                            {"is_active": True},
                            {"status": {"$exists": False}},
                            {"is_active": {"$exists": False}}
                        ]
                    }).to_list(length=None)
                    
                    for club in membership_clubs:
                        club_id = club.get("name_based_id")
                        if club_id:
                            all_clubs_dict[club_id] = {
                                **club,
                                "user_role_in_club": "member"
                            }
            
            # Format the result
            user_clubs = []
            for club_id, club_data in all_clubs_dict.items():
                user_clubs.append({
                    "club_id": club_id,
                    "club_name": club_data.get("name"),
                    "club_object_id": str(club_data["_id"]),
                    "user_role_in_club": club_data.get("user_role_in_club", "member").lower(),
                    "club_data": club_data
                })
            
            total_clubs_time = time.time() - clubs_start
            logger.info(f"✅ OPTIMIZED: Total clubs retrieval took {total_clubs_time:.3f}s - Final result: {len(user_clubs)} clubs")
            
            # Debug: Show final club roles
            for club in user_clubs:
                logger.info(f"🔍 Final club: {club['club_id']} - Role: {club['user_role_in_club']}")
            
            return user_clubs
            
        except Exception as e:
            logger.error(f"Error getting user clubs: {e}")
            # Fallback to original method if optimization fails
            logger.info("🔄 Falling back to original method...")
            return await self._get_user_clubs_original(user_id, user_role)
    
    async def _get_user_clubs_original(self, user_id: str, user_role: str) -> List[Dict]:
        """
        Original implementation as fallback - Get clubs that the user has access to based on their role
        Using separate queries for better reliability and error handling
        
        Args:
            user_id: User ID
            user_role: User's role (Captain, Moderator, Member)
            
        Returns:
            List of club dictionaries with access information
        """
        import time
        clubs_start = time.time()
        logger.info(f"🔍 Getting clubs for user {user_id} with role {user_role} (ORIGINAL FALLBACK)")
        
        user_clubs = []
        seen_club_ids = set()
        
        try:
            # Check for Captain role - Get all clubs they created
            captain_start = time.time()
            captain_clubs = await self.clubs_collection.find({
                "captain_id": user_id,
                "$or": [
                    {"status": "approved"},
                    {"is_active": True},
                    {"status": {"$exists": False}},
                    {"is_active": {"$exists": False}}
                ]
            }).to_list(length=None)
            captain_time = time.time() - captain_start
            logger.info(f"⏱️ Captain clubs query took {captain_time:.3f}s - Found {len(captain_clubs)} clubs")
            
            role_determination_start = time.time()
            for club in captain_clubs:
                club_id = club.get("name_based_id")
                if club_id and club_id not in seen_club_ids:
                    seen_club_ids.add(club_id)
                    
                    # Use the centralized role determination function
                    user_role_in_club = await self.my_clubs_service._determine_user_role_in_club(user_id, str(club["_id"]))
                    
                    # Only add clubs where user has a valid role
                    if user_role_in_club and user_role_in_club.lower() != "none":
                        user_clubs.append({
                            "club_id": club_id,
                            "club_name": club.get("name"),
                            "club_object_id": str(club["_id"]),
                            "user_role_in_club": user_role_in_club.lower(),
                            "club_data": club
                        })
            
            captain_role_time = time.time() - role_determination_start
            logger.info(f"⏱️ Captain role determination took {captain_role_time:.3f}s for {len(captain_clubs)} clubs")
            
            # Check for Moderator role - Get clubs where they are moderators
            moderator_start = time.time()
            moderator_clubs = await self.clubs_collection.find({
                "$or": [
                    {"moderators.user_id": user_id, "moderators.status": "active"},
                    {"detailed_moderators.user_id": user_id, "detailed_moderators.status": "active"}
                ],
                "$or": [
                    {"status": "approved"},
                    {"is_active": True},
                    {"status": {"$exists": False}},
                    {"is_active": {"$exists": False}}
                ]
            }).to_list(length=None)
            moderator_time = time.time() - moderator_start
            logger.info(f"⏱️ Moderator clubs query took {moderator_time:.3f}s - Found {len(moderator_clubs)} clubs")
            
            moderator_role_start = time.time()
            for club in moderator_clubs:
                club_id = club.get("name_based_id")
                if club_id and club_id not in seen_club_ids:
                    seen_club_ids.add(club_id)
                    
                    # Use the centralized role determination function
                    user_role_in_club = await self.my_clubs_service._determine_user_role_in_club(user_id, str(club["_id"]))
                    
                    # Only add clubs where user has a valid role
                    if user_role_in_club and user_role_in_club.lower() != "none":
                        user_clubs.append({
                            "club_id": club_id,
                            "club_name": club.get("name"),
                            "club_object_id": str(club["_id"]),
                            "user_role_in_club": user_role_in_club.lower(),
                            "club_data": club
                        })
            
            moderator_role_time = time.time() - moderator_role_start
            logger.info(f"⏱️ Moderator role determination took {moderator_role_time:.3f}s for {len(moderator_clubs)} clubs")
            
            # Check for Member role - Get clubs they joined (paid or trial)
            # Check memberships collection
            membership_start = time.time()
            memberships = await self.memberships_collection.find({
                "user_id": user_id,
                "subscription_status": "active"
            }).to_list(length=None)
            membership_time = time.time() - membership_start
            logger.info(f"⏱️ Memberships query took {membership_time:.3f}s - Found {len(memberships)} memberships")
            
            if memberships:
                membership_club_ids = [ObjectId(m.get("club_id")) for m in memberships if m.get("club_id")]
                if membership_club_ids:
                    membership_clubs = await self.clubs_collection.find({
                        "_id": {"$in": membership_club_ids},
                        "name_based_id": {"$nin": list(seen_club_ids)},
                        "$or": [
                            {"status": "approved"},
                            {"is_active": True},
                            {"status": {"$exists": False}},
                            {"is_active": {"$exists": False}}
                        ]
                    }).to_list(length=None)
                    
                    for club in membership_clubs:
                        club_id = club.get("name_based_id")
                        if club_id and club_id not in seen_club_ids:
                            seen_club_ids.add(club_id)
                            
                            # Use the centralized role determination function
                            user_role_in_club = await self.my_clubs_service._determine_user_role_in_club(user_id, str(club["_id"]))
                            
                            # Only add clubs where user has a valid role
                            if user_role_in_club and user_role_in_club.lower() != "none":
                                user_clubs.append({
                                    "club_id": club_id,
                                    "club_name": club.get("name"),
                                    "club_object_id": str(club["_id"]),
                                    "user_role_in_club": user_role_in_club.lower(),
                                    "club_data": club
                                })
            
            # Also check if user is in members or paid_members arrays
            member_clubs = await self.clubs_collection.find({
                "$or": [
                    {"members.user_id": user_id},
                    {"paid_members.user_id": user_id}
                ],
                "name_based_id": {"$nin": list(seen_club_ids)},
                "$or": [
                    {"status": "approved"},
                    {"is_active": True},
                    {"status": {"$exists": False}},
                    {"is_active": {"$exists": False}}
                ]
            }).to_list(length=None)
            
            for club in member_clubs:
                club_id = club.get("name_based_id")
                if club_id and club_id not in seen_club_ids:
                    seen_club_ids.add(club_id)
                    
                    # Use the centralized role determination function
                    user_role_in_club = await self.my_clubs_service._determine_user_role_in_club(user_id, str(club["_id"]))
                    
                    # Only add clubs where user has a valid role
                    if user_role_in_club and user_role_in_club.lower() != "none":
                        user_clubs.append({
                            "club_id": club_id,
                            "club_name": club.get("name"),
                            "club_object_id": str(club["_id"]),
                            "user_role_in_club": user_role_in_club.lower(),
                            "club_data": club
                        })
            
        except Exception as e:
            logger.error(f"Error getting user clubs: {e}")
            # Return empty list if there's an error
            return []
        
        total_clubs_time = time.time() - clubs_start
        logger.info(f"✅ ORIGINAL: Total clubs retrieval took {total_clubs_time:.3f}s - Final result: {len(user_clubs)} clubs")
        
        return user_clubs
    
    async def _get_picks_with_count_optimized(
        self, 
        user_clubs: List[Dict], 
        user_id: str,
        user_role: str,
        status_filter: Optional[str] = None,
        pick_type_filter: Optional[str] = None,
        result_filter: Optional[str] = None,
        sport_league_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict:
        """
        OPTIMIZED: Get picks and total count in a single aggregation pipeline
        This eliminates the need for separate count and data queries
        
        Args:
            user_clubs: List of user's clubs
            user_id: User ID for role-based filtering
            user_role: User's role (Captain, Moderator, Member)
            status_filter: Optional status filter
            pick_type_filter: Optional pick type filter (case-insensitive)
            result_filter: Optional result filter (pending/win/loss)
            sport_league_filter: Optional sport or league filter (searches both fields, case-insensitive)
            date_from: Optional start date filter
            date_to: Optional end date filter
            search: Optional search term
            page: Page number
            limit: Items per page
            
        Returns:
            Dict containing picks list and total count
        """
        if not user_clubs:
            return {"picks": [], "total": 0}
        
        club_ids = [club["club_id"] for club in user_clubs]
        
        # Build base match stage
        match_stage = {
            "club_id": {"$in": club_ids},
            "is_active": True
        }
        
        # Add role-based filtering based on user's role
        if user_role and user_role.lower() in ["member", "moderator", "captain"]:
            match_stage["submitted_by_role"] = {"$in": ["captain", "moderator"]}
        
        if status_filter:
            match_stage["status"] = status_filter
        
        # Make pick_type_filter case-insensitive using regex
        if pick_type_filter:
            match_stage["pick_type"] = {"$regex": f"^{pick_type_filter}$", "$options": "i"}
        
        # Add sport/league filter (searches both fields with case-insensitive match)
        if sport_league_filter:
            sport_league_condition = {
                "$or": [
                    {"sport": {"$regex": sport_league_filter, "$options": "i"}},
                    {"league": {"$regex": sport_league_filter, "$options": "i"}}
                ]
            }
            # If $and doesn't exist yet, add it; otherwise append to it
            if "$and" not in match_stage:
                match_stage["$and"] = []
            match_stage["$and"].append(sport_league_condition)
        
        # Add result filter
        if result_filter:
            if result_filter == "pending":
                result_condition = {
                    "$or": [
                        {"result": None},
                        {"result": {"$exists": False}},
                        {"status": "pending"}
                    ]
                }
                # If $and doesn't exist yet, add it; otherwise append to it
                if "$and" not in match_stage:
                    match_stage["$and"] = []
                match_stage["$and"].append(result_condition)
            else:
                match_stage["result"] = result_filter
        
        # Add date range filters (filter by created_at - when pick was created)
        if date_from or date_to:
            from datetime import timedelta
            date_filter = {}
            if date_from:
                date_filter["$gte"] = date_from
            if date_to:
                # Add 1 day and use $lt to include entire day (handles time portion)
                date_filter["$lt"] = date_to + timedelta(days=1)
            match_stage["created_at"] = date_filter
        
        # Add search filter
        if search and search.strip():
            search_term = search.strip()
            search_regex = {"$regex": search_term, "$options": "i"}
            search_conditions = [
                {"pick_type": search_regex},
                {"club_name": search_regex},
                {"league": search_regex},
                {"sport": search_regex},
                {"team1": search_regex},
                {"team2": search_regex},
                {"player_name": search_regex},
                {"parlay_picks.team1": search_regex},
                {"parlay_picks.team2": search_regex},
                {"parlay_picks.league": search_regex},
                {"parlay_picks.sport": search_regex},
                {"parlay_picks.player_name": search_regex}
            ]
            match_stage["$and"] = match_stage.get("$and", []) + [{"$or": search_conditions}]
        
        # Create aggregation pipeline
        def build_pipeline(page_number: int):
            return [
                {"$match": match_stage},
                {
                    "$facet": {
                        "picks": [
                            {"$sort": {"created_at": -1}},
                            {"$skip": max(page_number - 1, 0) * limit},
                            {"$limit": limit},
                            {
                                "$addFields": {
                                    "club_name": {
                                        "$let": {
                                            "vars": {
                                                "club": {
                                                    "$arrayElemAt": [
                                                        {
                                                            "$filter": {
                                                                "input": user_clubs,
                                                                "cond": {"$eq": ["$$this.club_id", "$club_id"]}
                                                            }
                                                        },
                                                        0
                                                    ]
                                                }
                                            },
                                            "in": "$$club.club_name"
                                        }
                                    },
                                    "user_role_in_club": {
                                        "$let": {
                                            "vars": {
                                                "club": {
                                                    "$arrayElemAt": [
                                                        {
                                                            "$filter": {
                                                                "input": user_clubs,
                                                                "cond": {"$eq": ["$$this.club_id", "$club_id"]}
                                                            }
                                                        },
                                                        0
                                                    ]
                                                }
                                            },
                                            "in": "$$club.user_role_in_club"
                                        }
                                    }
                                }
                            }
                        ],
                        "total_count": [
                            {"$count": "count"}
                        ]
                    }
                }
            ]
        
        async def execute_pipeline(page_number: int):
            aggregation = build_pipeline(page_number)
            agg_result = await self.picks_collection.aggregate(aggregation).to_list(length=1)
            if agg_result and agg_result[0]:
                picks_subset = agg_result[0].get("picks", [])
                total_count_array = agg_result[0].get("total_count", [])
                total_subset = total_count_array[0].get("count", 0) if total_count_array else 0
                return picks_subset, total_subset
            return [], 0

        picks, total_count = await execute_pipeline(page)

        # Adjust page if requested page exceeds available pages after filters (e.g., user was on page 2 then searched)
        adjusted_page = page
        if total_count > 0 and limit > 0:
            total_pages = math.ceil(total_count / limit)
            if page > total_pages:
                adjusted_page = total_pages
            if adjusted_page < 1:
                adjusted_page = 1

            if adjusted_page != page:
                picks, total_count = await execute_pipeline(adjusted_page)

        # Convert ObjectId to string
        formatted_picks = []
        for pick in picks:
            pick["_id"] = str(pick["_id"])
            if "club_object_id" in pick:
                pick["club_object_id"] = str(pick["club_object_id"])
            formatted_picks.append(pick)
        
        return {"picks": formatted_picks, "total": total_count, "page": adjusted_page}
    
    async def _get_picks_from_clubs(
        self, 
        user_clubs: List[Dict], 
        user_id: str,
        user_role: str,
        status_filter: Optional[str] = None,
        pick_type_filter: Optional[str] = None,
        result_filter: Optional[str] = None,
        sport_league_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> List[Dict]:
        """
        Get picks from user's clubs with proper role-based filtering
        Optimized for better query performance
        
        Args:
            user_clubs: List of user's clubs
            user_id: User ID for role-based filtering
            user_role: User's role (Captain, Moderator, Member)
            status_filter: Optional status filter
            pick_type_filter: Optional pick type filter (case-insensitive)
            result_filter: Optional result filter (pending/win/loss)
            sport_league_filter: Optional sport or league filter (searches both fields, case-insensitive)
            date_from: Optional start date filter
            date_to: Optional end date filter
            search: Optional search term
            page: Page number
            limit: Items per page
            
        Returns:
            List of pick dictionaries
        """
        if not user_clubs:
            return []
        
        # Build query for picks
        club_ids = [club["club_id"] for club in user_clubs]
        
        query = {
            "club_id": {"$in": club_ids},
            "is_active": True
        }
        
        # Add role-based filtering based on user's role
        # Only add role filtering if we have a valid user_role
        if user_role and user_role.lower() in ["member", "moderator", "captain"]:
            # All roles can see picks from captains and moderators
            query["submitted_by_role"] = {"$in": ["captain", "moderator"]}
        
        if status_filter:
            query["status"] = status_filter
        
        # Make pick_type_filter case-insensitive using regex
        if pick_type_filter:
            query["pick_type"] = {"$regex": f"^{pick_type_filter}$", "$options": "i"}
        
        # Add sport/league filter (searches both fields with case-insensitive match)
        if sport_league_filter:
            if "$and" not in query:
                query["$and"] = []
            query["$and"].append({
                "$or": [
                    {"sport": {"$regex": sport_league_filter, "$options": "i"}},
                    {"league": {"$regex": sport_league_filter, "$options": "i"}}
                ]
            })
        
        # Add result filter
        if result_filter:
            if result_filter == "pending":
                # For pending results, we want picks where result is null or status is pending
                query["$and"] = [
                    query.get("$and", []),
                    {"$or": [
                        {"result": None},
                        {"result": {"$exists": False}},
                        {"status": "pending"}
                    ]}
                ]
            else:
                # For win/loss, we want picks with that specific result
                query["result"] = result_filter
        
        # Add date range filters (filter by created_at - when pick was created)
        if date_from or date_to:
            from datetime import timedelta
            date_filter = {}
            if date_from:
                date_filter["$gte"] = date_from
            if date_to:
                # Add 1 day and use $lt to include entire day (handles time portion)
                date_filter["$lt"] = date_to + timedelta(days=1)
            query["created_at"] = date_filter
        
        # Add search filter
        if search and search.strip():
            search_term = search.strip()
            search_regex = {"$regex": search_term, "$options": "i"}
            search_conditions = [
                {"pick_type": search_regex},
                {"club_name": search_regex},
                {"league": search_regex},
                {"sport": search_regex},
                {"team1": search_regex},
                {"team2": search_regex},
                {"player_name": search_regex},
                {"parlay_picks.team1": search_regex},
                {"parlay_picks.team2": search_regex},
                {"parlay_picks.league": search_regex},
                {"parlay_picks.sport": search_regex},
                {"parlay_picks.player_name": search_regex}
            ]
            
            # If we already have $and conditions, add search to them
            if "$and" in query:
                query["$and"].append({"$or": search_conditions})
            else:
                query["$or"] = search_conditions
        
        # Get picks with pagination
        skip = (page - 1) * limit
        cursor = self.picks_collection.find(query)
        cursor = cursor.sort("created_at", -1).skip(skip).limit(limit)
        picks = await cursor.to_list(length=limit)
        
        # Convert ObjectId to string and add club info
        for pick in picks:
            pick["_id"] = str(pick["_id"])
            if "club_object_id" in pick:
                pick["club_object_id"] = str(pick["club_object_id"])
            
            # Add club information
            club_id = pick.get("club_id")
            club_info = next((club for club in user_clubs if club["club_id"] == club_id), None)
            if club_info:
                pick["club_name"] = club_info["club_name"]
                pick["user_role_in_club"] = club_info["user_role_in_club"]
        
        return picks
    
    async def _get_total_picks_count(
        self, 
        user_clubs: List[Dict], 
        user_id: str,
        user_role: str,
        status_filter: Optional[str] = None,
        pick_type_filter: Optional[str] = None,
        result_filter: Optional[str] = None,
        sport_league_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None
    ) -> int:
        """
        Get total count of picks for pagination with proper role-based filtering
        Optimized for better query performance
        
        Args:
            user_clubs: List of user's clubs
            user_id: User ID for role-based filtering
            user_role: User's role (Captain, Moderator, Member)
            status_filter: Optional status filter
            pick_type_filter: Optional pick type filter (case-insensitive)
            result_filter: Optional result filter (pending/win/loss)
            sport_league_filter: Optional sport or league filter (searches both fields, case-insensitive)
            date_from: Optional start date filter
            date_to: Optional end date filter
            search: Optional search term
            
        Returns:
            Total count of picks
        """
        if not user_clubs:
            return 0
        
        club_ids = [club["club_id"] for club in user_clubs]
        
        query = {
            "club_id": {"$in": club_ids},
            "is_active": True
        }
        
        # Add role-based filtering based on user's role
        # Only add role filtering if we have a valid user_role
        if user_role and user_role.lower() in ["member", "moderator", "captain"]:
            # All roles can see picks from captains and moderators
            query["submitted_by_role"] = {"$in": ["captain", "moderator"]}
        
        if status_filter:
            query["status"] = status_filter
        
        # Make pick_type_filter case-insensitive using regex
        if pick_type_filter:
            query["pick_type"] = {"$regex": f"^{pick_type_filter}$", "$options": "i"}
        
        # Add sport/league filter (searches both fields with case-insensitive match)
        if sport_league_filter:
            if "$and" not in query:
                query["$and"] = []
            query["$and"].append({
                "$or": [
                    {"sport": {"$regex": sport_league_filter, "$options": "i"}},
                    {"league": {"$regex": sport_league_filter, "$options": "i"}}
                ]
            })
        
        # Add result filter
        if result_filter:
            if result_filter == "pending":
                # For pending results, we want picks where result is null or status is pending
                query["$and"] = [
                    query.get("$and", []),
                    {"$or": [
                        {"result": None},
                        {"result": {"$exists": False}},
                        {"status": "pending"}
                    ]}
                ]
            else:
                # For win/loss, we want picks with that specific result
                query["result"] = result_filter
        
        # Add date range filters (filter by created_at - when pick was created)
        if date_from or date_to:
            from datetime import timedelta
            date_filter = {}
            if date_from:
                date_filter["$gte"] = date_from
            if date_to:
                # Add 1 day and use $lt to include entire day (handles time portion)
                date_filter["$lt"] = date_to + timedelta(days=1)
            query["created_at"] = date_filter
        
        # Add search filter
        if search and search.strip():
            search_term = search.strip()
            search_regex = {"$regex": search_term, "$options": "i"}
            search_conditions = [
                {"pick_type": search_regex},
                {"club_name": search_regex},
                {"league": search_regex},
                {"sport": search_regex},
                {"team1": search_regex},
                {"team2": search_regex},
                {"player_name": search_regex},
                {"parlay_picks.team1": search_regex},
                {"parlay_picks.team2": search_regex},
                {"parlay_picks.league": search_regex},
                {"parlay_picks.sport": search_regex},
                {"parlay_picks.player_name": search_regex}
            ]
            
            # If we already have $and conditions, add search to them
            if "$and" in query:
                query["$and"].append({"$or": search_conditions})
            else:
                query["$or"] = search_conditions
        
        return await self.picks_collection.count_documents(query)
    
    async def get_my_pick_by_id(self, user_id: str, pick_id: str) -> Dict:
        """
        Get a specific pick by ID for a user based on their role and club memberships
        
        Args:
            user_id: User ID
            pick_id: Pick ID to retrieve
            
        Returns:
            Dict containing pick data
            
        Raises:
            HTTPException if pick not found or user doesn't have access
        """
        try:
            from bson import ObjectId
            
            # Validate pick_id format
            if not ObjectId.is_valid(pick_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid pick ID format"
                )
            
            # Get user details
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            user_role = user.get("role", "Member")
            
            # Get user's clubs based on their role
            user_clubs = await self._get_user_clubs(user_id, user_role)
            
            if not user_clubs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No clubs found for user"
                )
            
            # Get club IDs that user has access to
            club_ids = [club["club_id"] for club in user_clubs]
            
            # Build query with role-based filtering
            query = {
                "_id": ObjectId(pick_id),
                "club_id": {"$in": club_ids},
                "is_active": True
            }
            
            # Add role-based filtering based on user's role
            if user_role.lower() == "member":
                # Members can only see picks from captains and moderators
                query["submitted_by_role"] = {"$in": ["captain", "moderator"]}
            elif user_role.lower() == "moderator":
                # Moderators can see picks from captains and other moderators in their clubs
                query["submitted_by_role"] = {"$in": ["captain", "moderator"]}
            elif user_role.lower() == "captain":
                # Captains can see all picks from their clubs (captain + moderator picks)
                query["submitted_by_role"] = {"$in": ["captain", "moderator"]}
            
            # Find the pick
            pick = await self.picks_collection.find_one(query)
            
            if not pick:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Pick not found or you don't have access to this pick"
                )
            
            # Convert ObjectId to string
            pick["_id"] = str(pick["_id"])
            if "club_object_id" in pick:
                pick["club_object_id"] = str(pick["club_object_id"])
            
            # Add club information
            club_id = pick.get("club_id")
            club_info = next((club for club in user_clubs if club["club_id"] == club_id), None)
            if club_info:
                pick["club_name"] = club_info["club_name"]
                pick["user_role_in_club"] = club_info["user_role_in_club"]
            
            return pick
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting pick by ID for user {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get pick: {str(e)}"
            )
    
    async def get_my_picks_summary(self, user_id: str) -> Dict:
        """
        Get summary statistics for user's picks
        
        Args:
            user_id: User ID
            
        Returns:
            Dict containing summary statistics
        """
        try:
            # Get user details
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            user_role = user.get("role", "Member")
            
            # Get user's clubs
            user_clubs = await self._get_user_clubs(user_id, user_role)
            
            if not user_clubs:
                return {
                    "total_picks": 0,
                    "pending_picks": 0,
                    "completed_picks": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_percentage": 0.0,
                    "clubs_count": 0,
                    "user_role": user_role
                }
            
            club_ids = [club["club_id"] for club in user_clubs]
            
            # Build match stage with role-based filtering
            match_stage = {
                "club_id": {"$in": club_ids},
                "is_active": True
            }
            
            # Add role-based filtering based on user's role
            if user_role.lower() == "member":
                # Members can only see picks from captains and moderators
                match_stage["submitted_by_role"] = {"$in": ["captain", "moderator"]}
            elif user_role.lower() == "moderator":
                # Moderators can see picks from captains and other moderators in their clubs
                match_stage["submitted_by_role"] = {"$in": ["captain", "moderator"]}
            elif user_role.lower() == "captain":
                # Captains can see all picks from their clubs (captain + moderator picks)
                match_stage["submitted_by_role"] = {"$in": ["captain", "moderator"]}
            
            # Get statistics using aggregation
            pipeline = [
                {
                    "$match": match_stage
                },
                {
                    "$group": {
                        "_id": None,
                        "total_picks": {"$sum": 1},
                        "pending_picks": {
                            "$sum": {
                                "$cond": [{"$eq": ["$status", "pending"]}, 1, 0]
                            }
                        },
                        "completed_picks": {
                            "$sum": {
                                "$cond": [{"$eq": ["$status", "completed"]}, 1, 0]
                            }
                        },
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
            
            result = await self.picks_collection.aggregate(pipeline).to_list(length=1)
            
            if result:
                stats = result[0]
                wins = stats.get("wins", 0)
                losses = stats.get("losses", 0)
                completed = wins + losses
                win_percentage = (wins / completed * 100) if completed > 0 else 0.0
                
                return {
                    "total_picks": stats.get("total_picks", 0),
                    "pending_picks": stats.get("pending_picks", 0),
                    "completed_picks": stats.get("completed_picks", 0),
                    "wins": wins,
                    "losses": losses,
                    "win_percentage": round(win_percentage, 2),
                    "clubs_count": len(user_clubs),
                    "user_role": user_role
                }
            else:
                return {
                    "total_picks": 0,
                    "pending_picks": 0,
                    "completed_picks": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_percentage": 0.0,
                    "clubs_count": len(user_clubs),
                    "user_role": user_role
                }
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting picks summary for user {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get picks summary: {str(e)}"
            )

    async def export_my_picks_csv(
        self,
        user_id: str,
        status_filter: Optional[str] = None,
        pick_type_filter: Optional[str] = None,
        result_filter: Optional[str] = None,
        sport_league_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None
    ) -> str:
        """
        Export user's picks to CSV format
        
        Args:
            user_id: User ID
            status_filter: Filter by status (pending/completed)
            pick_type_filter: Filter by pick type (case-insensitive)
            result_filter: Filter by result (pending/win/loss)
            sport_league_filter: Filter by sport or league (searches both fields, case-insensitive)
            date_from: Filter picks from this date
            date_to: Filter picks to this date
            search: Search by pick_type, club_name, or league
            
        Returns:
            CSV content as string
        """
        try:
            import csv
            import io
            from bson import ObjectId
            
            # Get user details first
            user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            user_role = user.get("role", "Member")
            
            # Get user's clubs
            user_clubs = await self._get_user_clubs(user_id, user_role)
            if not user_clubs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No clubs found for user"
                )
            
            # Get picks from clubs
            picks = await self._get_picks_from_clubs(
                user_clubs=user_clubs,
                user_id=user_id,
                user_role=user_role,
                status_filter=status_filter,
                pick_type_filter=pick_type_filter,
                result_filter=result_filter,
                sport_league_filter=sport_league_filter,
                date_from=date_from,
                date_to=date_to,
                search=search,
                page=1,
                limit=10000  # Large limit for export
            )
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Club Name',
                'League',
                'Bet Source',
                'Pick Type',
                'Status',
                'Result',
                'Player Name',
                'Team 1',
                'Team 2'
            ])
            
            # Write data rows
            for pick in picks:
                pick_type = (pick.get('pick_type') or '').lower()
                team1 = pick.get('team1', '') or ''
                team2 = pick.get('team2', '') or ''
                player_name = pick.get('player_name', '') or ''

                if pick_type == 'parlay':
                    parlay_picks = pick.get('parlay_picks') or []
                    if parlay_picks:
                        first_parlay_pick = parlay_picks[0] or {}
                        team1 = first_parlay_pick.get('team1', team1) or team1
                        team2 = first_parlay_pick.get('team2', team2) or team2
                        player_name = first_parlay_pick.get('player_name', player_name) or player_name

                league_value = pick.get('league')
                sport_value = pick.get('sport')
                league = league_value.capitalize() if isinstance(league_value, str) else ''
                sport = sport_value.capitalize() if isinstance(sport_value, str) else ''
                sport_league = f"{sport} - {league}" if sport and league else league or sport
                
                # Safely handle None values for capitalize()
                pick_status = pick.get('status') or ''
                result_value = pick.get('result') or 'Pending'
                result_text = ""
                if result_value == "win":
                    result_text = "Win"
                elif result_value == "loss":
                    result_text="Lost"
                else:
                    result_text = "Pending"
                
                writer.writerow([
                    pick.get('club_name', '').capitalize(),
                    sport_league,
                    pick.get('bet_source', '').capitalize(),
                    pick.get('pick_type', '').capitalize()  ,
                    pick_status.capitalize() if pick_status else '',
                    result_text,
                    player_name,
                    team1,
                    team2
                ])
            
            return output.getvalue()
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error exporting picks to CSV for user {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to export picks: {str(e)}"
            )


# Singleton instance
_service_instance = None

def get_my_picks_service() -> MyPicksService:
    """Get singleton instance of MyPicksService"""
    global _service_instance
    if _service_instance is None:
        _service_instance = MyPicksService()
    return _service_instance
