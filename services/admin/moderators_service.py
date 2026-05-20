"""
Moderator Management Service

This service handles all moderator-related operations including:
- Fetching moderator lists with filters and pagination
- Search functionality across moderator and captain data
- Club assignment aggregation
- Data formatting and validation
"""

import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId
from .db import (
    clubs_collection, club_memberships_collection, users_collection,
    search_logs_collection
)
from .models import (
    ModeratorListRequest, ModeratorListResponse, ModeratorListItem,
    ModeratorClubAssignment, ModeratorListPagination, ModeratorSearchLog,
    ModeratorStatus, ModeratorRole, ModeratorSortField, ModeratorSortOrder
)

class AdminModeratorsService:
    def __init__(self):
        self.clubs_collection = clubs_collection
        self.club_memberships_collection = club_memberships_collection
        self.users_collection = users_collection
        self.search_logs_collection = search_logs_collection

    async def get_moderators_list(self, request: ModeratorListRequest, admin_email: str, ip_address: Optional[str] = None) -> ModeratorListResponse:
        """
        Get comprehensive moderator list with filtering, search, and pagination
        
        Args:
            request: ModeratorListRequest with filters and pagination
            admin_email: Email of admin making the request
            ip_address: IP address for audit logging
            
        Returns:
            ModeratorListResponse with formatted moderator data
        """
        start_time = time.time()
        
        try:
            print(f"DEBUG: Fetching moderators list with filters: {request.dict()}")
            
            # Build aggregation pipeline for moderators
            pipeline = await self._build_moderator_aggregation_pipeline(request)
            
            # Execute aggregation to get moderators with club assignments
            moderators_data = await self._execute_moderator_aggregation(pipeline, request)
            
            # Format the response data
            formatted_moderators = await self._format_moderator_data(moderators_data)
            
            # Get pagination metadata
            pagination = await self._get_pagination_metadata(request, len(formatted_moderators))
            
            # Get summary statistics
            stats = await self._get_moderator_statistics(request)
            
            end_time = time.time()
            response_time = round((end_time - start_time) * 1000, 2)
            
            # Log the search operation
            await self._log_moderator_search(admin_email, ip_address, request, len(formatted_moderators), response_time)
            
            return ModeratorListResponse(
                success=True,
                message=f"Retrieved {len(formatted_moderators)} moderators successfully",
                data=formatted_moderators,
                pagination=pagination,
                filters_applied=self._get_applied_filters(request),
                total_moderators=stats['total'],
                active_moderators=stats['active'],
                inactive_moderators=stats['inactive'],
                response_time_ms=response_time
            )
            
        except Exception as e:
            print(f"Error in get_moderators_list: {e}")
            return ModeratorListResponse(
                success=False,
                message=f"Failed to retrieve moderators: {str(e)}",
                data=[],
                pagination=ModeratorListPagination(
                    current_page=request.page,
                    total_pages=0,
                    total_records=0,
                    records_per_page=request.limit,
                    has_next=False,
                    has_previous=False
                ),
                filters_applied={},
                total_moderators=0,
                active_moderators=0,
                inactive_moderators=0
            )

    async def _build_moderator_aggregation_pipeline(self, request: ModeratorListRequest) -> List[Dict[str, Any]]:
        """Build MongoDB aggregation pipeline for moderator data with enhanced filtering and sorting"""
        
        pipeline = []
        
        # Stage 1: Match moderator roles in club_memberships
        match_stage = {
            "$match": {
                "role": {"$in": ["moderator", "analyst", "editor"]},
                "is_active": True
            }
        }
        
        # Add basic club_id filter if specified (backward compatibility)
        if request.club_id:
            match_stage["$match"]["club_id"] = request.club_id
            
        pipeline.append(match_stage)
        
        # Stage 2: Lookup user details
        pipeline.append({
            "$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user_data"
            }
        })
        
        # Stage 3: Unwind user data
        pipeline.append({
            "$unwind": {
                "path": "$user_data",
                "preserveNullAndEmptyArrays": False
            }
        })
        
        # Stage 4: Filter out deleted/inactive users
        pipeline.append({
            "$match": {
                "user_data.is_deleted": {"$ne": True}
            }
        })
        
        # Stage 5: Lookup club details
        pipeline.append({
            "$lookup": {
                "from": "clubs",
                "localField": "club_id",
                "foreignField": "_id",
                "as": "club_data"
            }
        })
        
        # Stage 6: Unwind club data
        pipeline.append({
            "$unwind": {
                "path": "$club_data",
                "preserveNullAndEmptyArrays": False
            }
        })
        
        # Stage 7: Filter out deleted clubs
        pipeline.append({
            "$match": {
                "club_data.is_deleted": {"$ne": True}
            }
        })
        
        # Stage 8: Lookup captain details
        pipeline.append({
            "$lookup": {
                "from": "users",
                "localField": "club_data.captain_id",
                "foreignField": "_id",
                "as": "captain_data"
            }
        })
        
        # Stage 9: Add captain data (may be empty)
        pipeline.append({
            "$addFields": {
                "captain_info": {
                    "$arrayElemAt": ["$captain_data", 0]
                }
            }
        })
        
        # Stage 10: Apply enhanced club filter if provided
        if request.club:
            # Support both club ID and club name partial matching
            club_match_conditions = []
            
            # Try to match as ObjectId first
            try:
                from bson import ObjectId
                if len(request.club) == 24:  # Potential ObjectId
                    club_match_conditions.append({"club_data._id": ObjectId(request.club)})
            except:
                pass
            
            # Add partial name matching
            club_name_regex = {"$regex": request.club, "$options": "i"}
            club_match_conditions.append({"club_data.name": club_name_regex})
            
            if club_match_conditions:
                pipeline.append({
                    "$match": {
                        "$or": club_match_conditions
                    }
                })
        
        # Stage 11: Apply assigned_by filter if provided
        if request.assigned_by:
            # Support both captain ID and captain name partial matching
            assigned_by_match_conditions = []
            
            # Try to match as ObjectId first
            try:
                from bson import ObjectId
                if len(request.assigned_by) == 24:  # Potential ObjectId
                    assigned_by_match_conditions.append({"captain_info._id": ObjectId(request.assigned_by)})
            except:
                pass
            
            # Add partial name matching
            captain_name_regex = {"$regex": request.assigned_by, "$options": "i"}
            assigned_by_match_conditions.append({"captain_info.full_name": captain_name_regex})
            assigned_by_match_conditions.append({"captain_info.email": captain_name_regex})
            
            if assigned_by_match_conditions:
                pipeline.append({
                    "$match": {
                        "$or": assigned_by_match_conditions
                    }
                })
        
        # Stage 12: Apply search filter if provided
        if request.search:
            search_regex = {"$regex": request.search, "$options": "i"}
            pipeline.append({
                "$match": {
                    "$or": [
                        {"user_data.full_name": search_regex},
                        {"user_data.email": search_regex},
                        {"captain_info.full_name": search_regex},
                        {"captain_info.email": search_regex}
                    ]
                }
            })
        
        # Stage 12.1: Apply individual name search filter if provided
        if request.name:
            name_regex = {"$regex": request.name, "$options": "i"}
            pipeline.append({
                "$match": {
                    "user_data.full_name": name_regex
                }
            })
        
        # Stage 12.2: Apply individual email search filter if provided
        if request.email:
            email_regex = {"$regex": request.email, "$options": "i"}
            pipeline.append({
                "$match": {
                    "user_data.email": email_regex
                }
            })
        
        # Stage 13: Group by user to aggregate club assignments
        pipeline.append({
            "$group": {
                "_id": "$user_data._id",
                "user_data": {"$first": "$user_data"},
                "clubs": {
                    "$push": {
                        "club_id": {"$toString": "$club_data._id"},
                        "club_name": "$club_data.name",
                        "captain_name": {"$ifNull": ["$captain_info.full_name", "Unknown"]},
                        "captain_email": {"$ifNull": ["$captain_info.email", None]},
                        "captain_id": {"$toString": "$captain_info._id"},
                        "role": "$role",
                        "joined_date": "$joined_date",
                        "subscription_status": "$subscription_status",
                        "is_active": "$is_active"
                    }
                },
                "total_clubs": {"$sum": 1},
                "last_activity": {"$max": "$joined_date"},
                "first_join_date": {"$min": "$joined_date"}
            }
        })
        
        # Stage 14: Apply status filter if provided
        if request.status:
            is_active = request.status == ModeratorStatus.ACTIVE
            pipeline.append({
                "$match": {
                    "user_data.is_active": is_active,
                    "user_data.is_verified": is_active  # Also check verification status
                }
            })
        
        # Stage 15: Add computed fields for sorting
        pipeline.append({
            "$addFields": {
                "sort_name": {"$toLower": "$user_data.full_name"},
                "sort_email": {"$toLower": "$user_data.email"},
                "sort_date_joined": "$first_join_date",
                "sort_club_count": "$total_clubs",
                "sort_status": {
                    "$cond": {
                        "if": {"$and": [
                            {"$eq": ["$user_data.is_active", True]},
                            {"$eq": ["$user_data.is_verified", True]}
                        ]},
                        "then": 1,
                        "else": 0
                    }
                }
            }
        })
        
        # Stage 16: Apply dynamic sorting based on request
        sort_field = self._get_sort_field(request.sort_by)
        sort_order = 1 if request.order == ModeratorSortOrder.ASC else -1
        
        pipeline.append({
            "$sort": {
                sort_field: sort_order,
                "_id": 1  # Secondary sort for consistency
            }
        })
        
        return pipeline

    def _get_sort_field(self, sort_by: ModeratorSortField) -> str:
        """Map sort field enum to actual database field"""
        sort_field_mapping = {
            ModeratorSortField.NAME: "sort_name",
            ModeratorSortField.EMAIL: "sort_email", 
            ModeratorSortField.DATE_JOINED: "sort_date_joined",
            ModeratorSortField.CLUB_COUNT: "sort_club_count",
            ModeratorSortField.STATUS: "sort_status"
        }
        return sort_field_mapping.get(sort_by, "sort_date_joined")

    async def _execute_moderator_aggregation(self, pipeline: List[Dict[str, Any]], request: ModeratorListRequest) -> List[Dict[str, Any]]:
        """Execute the aggregation pipeline with pagination"""
        
        # Add pagination stages
        skip_stage = {"$skip": (request.page - 1) * request.limit}
        limit_stage = {"$limit": request.limit}
        
        pipeline.extend([skip_stage, limit_stage])
        
        # Execute aggregation
        cursor = self.club_memberships_collection.aggregate(pipeline)
        results = []
        
        async for doc in cursor:
            results.append(doc)
        
        print(f"DEBUG: Aggregation returned {len(results)} moderators")
        return results

    async def _format_moderator_data(self, moderators_data: List[Dict[str, Any]]) -> List[ModeratorListItem]:
        """Format raw aggregation data into ModeratorListItem objects"""
        
        formatted_moderators = []
        
        for moderator_doc in moderators_data:
            user_data = moderator_doc.get("user_data", {})
            clubs_data = moderator_doc.get("clubs", [])
            
            # Format club assignments
            club_assignments = []
            for club in clubs_data:
                club_assignment = ModeratorClubAssignment(
                    club_id=club.get("club_id"),
                    club_name=club.get("club_name"),
                    captain_name=club.get("captain_name"),
                    captain_email=club.get("captain_email"),
                    role=ModeratorRole(club.get("role", "moderator")),
                    joined_date=self._format_date(club.get("joined_date")),
                    status="active" if club.get("is_active") else "inactive",
                    subscription_status=club.get("subscription_status", "unknown")
                )
                club_assignments.append(club_assignment)
            
            # Determine moderator status
            is_active = user_data.get("is_active", False) and user_data.get("is_verified", False)
            status = ModeratorStatus.ACTIVE if is_active else ModeratorStatus.INACTIVE
            
            # Format moderator item
            moderator_item = ModeratorListItem(
                moderator_id=str(user_data.get("_id")),
                name=user_data.get("full_name", "Unknown"),
                email=user_data.get("email", "--"),
                phone=user_data.get("phone"),
                status=status,
                total_clubs=moderator_doc.get("total_clubs", 0),
                clubs=club_assignments,
                last_active=self._format_date(moderator_doc.get("last_activity")),
                created_at=self._format_date(user_data.get("created_at")),
                avatar_url=user_data.get("profile_picture")
            )
            
            formatted_moderators.append(moderator_item)
        
        return formatted_moderators

    async def _get_pagination_metadata(self, request: ModeratorListRequest, current_results_count: int) -> ModeratorListPagination:
        """Calculate pagination metadata"""
        
        # Get total count with same filters (without pagination)
        count_pipeline = await self._build_moderator_aggregation_pipeline(request)
        count_pipeline.append({"$count": "total"})
        
        cursor = self.club_memberships_collection.aggregate(count_pipeline)
        count_result = await cursor.to_list(length=1)
        total_records = count_result[0]["total"] if count_result else 0
        
        total_pages = (total_records + request.limit - 1) // request.limit
        has_next = request.page < total_pages
        has_previous = request.page > 1
        
        return ModeratorListPagination(
            current_page=request.page,
            total_pages=total_pages,
            total_records=total_records,
            records_per_page=request.limit,
            has_next=has_next,
            has_previous=has_previous
        )

    async def _get_moderator_statistics(self, request: ModeratorListRequest) -> Dict[str, int]:
        """Get overall moderator statistics"""
        
        try:
            # Count all moderators
            pipeline = [
                {
                    "$match": {
                        "role": {"$in": ["moderator", "analyst", "editor"]},
                        "is_active": True
                    }
                },
                {
                    "$lookup": {
                        "from": "users",
                        "localField": "user_id",
                        "foreignField": "_id",
                        "as": "user_data"
                    }
                },
                {
                    "$unwind": "$user_data"
                },
                {
                    "$match": {
                        "user_data.is_deleted": {"$ne": True}
                    }
                },
                {
                    "$group": {
                        "_id": "$user_data._id",
                        "user_data": {"$first": "$user_data"}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total": {"$sum": 1},
                        "active": {
                            "$sum": {
                                "$cond": [
                                    {"$and": [
                                        {"$eq": ["$user_data.is_active", True]},
                                        {"$eq": ["$user_data.is_verified", True]}
                                    ]},
                                    1,
                                    0
                                ]
                            }
                        }
                    }
                }
            ]
            
            cursor = self.club_memberships_collection.aggregate(pipeline)
            stats_result = await cursor.to_list(length=1)
            
            if stats_result:
                stats = stats_result[0]
                total = stats.get("total", 0)
                active = stats.get("active", 0)
                inactive = total - active
            else:
                total = active = inactive = 0
            
            return {
                "total": total,
                "active": active,
                "inactive": inactive
            }
            
        except Exception as e:
            print(f"Error getting moderator statistics: {e}")
            return {"total": 0, "active": 0, "inactive": 0}

    def _format_date(self, date_obj) -> Optional[str]:
        """Format datetime to DD MMM YYYY format"""
        if not date_obj:
            return None
        
        try:
            if isinstance(date_obj, datetime):
                return date_obj.strftime("%d %b %Y")
            return None
        except:
            return None

    def _get_applied_filters(self, request: ModeratorListRequest) -> Dict[str, Any]:
        """Get dictionary of applied filters for response"""
        filters = {}
        
        if request.search:
            filters["search"] = request.search
        if request.name:
            filters["name"] = request.name
        if request.email:
            filters["email"] = request.email
        if request.status:
            filters["status"] = request.status.value
        if request.club_id:
            filters["club_id"] = request.club_id
        if request.club:
            filters["club"] = request.club
        if request.assigned_by:
            filters["assigned_by"] = request.assigned_by
        
        # Include sorting parameters
        filters["sort_by"] = request.sort_by.value
        filters["order"] = request.order.value
        filters["page"] = request.page
        filters["limit"] = request.limit
        
        return filters

    async def _log_moderator_search(self, admin_email: str, ip_address: Optional[str], 
                                  request: ModeratorListRequest, results_count: int, 
                                  response_time_ms: float):
        """Log moderator search operation for audit purposes"""
        try:
            search_log = {
                "_id": ObjectId(),
                "search_id": str(ObjectId()),
                "admin_email": admin_email,
                "search_filters": request.dict(),
                "results_count": results_count,
                "response_time_ms": response_time_ms,
                "timestamp": datetime.utcnow(),
                "ip_address": ip_address
            }
            
            await self.search_logs_collection.insert_one(search_log)
            
        except Exception as e:
            print(f"Error logging moderator search: {e}")

# Global service instance
admin_moderators_service = AdminModeratorsService()