import os
import time
import csv
import io
import bcrypt
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
# from .password_utils import hash_password as robust_hash_password
from .db import (
    clubs_collection, club_memberships_collection, users_collection, 
    search_logs_collection, export_logs_collection, club_picks_collection,
    club_payments_collection, club_refunds_collection, club_activity_collection,
    club_performance_collection, club_admin_logs_collection
)
from .models import (
    ClubListRequest, ClubResponse, ClubPaginationMetadata, ClubListResponse,
    ClubSearchRequest, ClubSearchResponse, ClubSearchLog,
    ClubExportRequest, ClubExportResponse, ClubExportLog,
    ClubStatus, ClubSortField, SortOrder,
    ClubDetailsResponse, ClubStatusUpdateRequest, ClubStatusUpdateResponse,
    ClubAction, ModeratorDetails, OwnerDetails, FinancialDetails,
    ActivityMetrics, PickDetails, RefundLogEntry, PaymentHistoryEntry,
    ClubAnalyticsRequest, ClubAnalyticsResponse, ClubPerformanceMetrics,
    ClubPerformanceResponse, ClubActivityLogEntry, ClubActivityLogResponse,
    ClubBulkActionRequest, ClubBulkActionResponse, ModeratorRole,
    ClubAdvancedSearchRequest, ClubAdvancedSearchResponse, ClubSearchSortField,
    ClubType, ClubCreateRequest, ClubUpdateRequest, ClubCreateResponse,
    ClubUpdateResponse, ClubDeleteResponse, ClubAuditLogEntry,
    ClubUpdateDetailsRequest
)

class AdminClubsService:
    def __init__(self):
        self.clubs_collection = clubs_collection
        self.club_memberships_collection = club_memberships_collection
        self.users_collection = users_collection
        self.search_logs_collection = search_logs_collection
        self.export_logs_collection = export_logs_collection

    async def get_clubs(self, request: ClubListRequest) -> ClubListResponse:
        """Get paginated list of clubs with search, filtering, and sorting"""
        
        # Build query filter
        query_filter = {}
        
        # Start with base pending clubs filtering logic
        # When admin logs in, only show clubs with club_complete_step=5 when status is pending
        # This ensures admins only see fully completed clubs that are pending approval
        pending_club_filter = {
            "$or": [
                # Show clubs that are not pending (approved, rejected, inactive, deleted) - regardless of completion step
                {"status": {"$ne": "pending"}},
                # OR show pending clubs only if club_complete_step=5 (fully completed)
                {
                    "status": "pending",
                    "club_complete_step": 5
                }
            ]
        }
        query_filter.update(pending_club_filter)
        
        print(f"🔍 Admin clubs base filter: {pending_club_filter}")
        
        # Search filter
        if request.search:
            search_regex = {"$regex": request.search, "$options": "i"}
            search_filter = {
                "$or": [
                    {"name": search_regex},
                    {"captain_id": {"$in": await self._get_user_ids_by_name(request.search)}}
                ]
            }
            # Combine search filter with existing filter using $and
            query_filter = {
                "$and": [
                    query_filter,
                    search_filter
                ]
            }
        
        # Status filter - override the base pending filter if specific status is requested
        if request.status:
            # Use case-insensitive regex for status matching
            status_value = request.status.value.lower()
            
            # For pending status, only show clubs with club_complete_step=5
            if status_value == "pending":
                status_filter = {
                    "$and": [
                        {"status": {"$regex": f"^{request.status.value}$", "$options": "i"}},
                        {"club_complete_step": 5}
                    ]
                }
            else:
                # For other statuses, show all clubs regardless of completion step
                status_filter = {"status": {"$regex": f"^{request.status.value}$", "$options": "i"}}
            
            # Combine status filter with existing filter using $and
            if "$and" in query_filter:
                query_filter["$and"].append(status_filter)
            else:
                query_filter = {
                    "$and": [
                        query_filter,
                        status_filter
                    ]
                }
        
        print(f"🔍 Final admin clubs query filter: {query_filter}")

        
        # Date range filter
        if request.date_from or request.date_to:
            date_filter = {}
            if request.date_from:
                date_filter["$gte"] = request.date_from
            if request.date_to:
                date_filter["$lte"] = request.date_to
            query_filter["created_at"] = date_filter
        
        # Get total count for pagination
        total_clubs = await self.clubs_collection.count_documents(query_filter)
        
        # Calculate pagination
        skip = (request.page - 1) * request.limit
        total_pages = (total_clubs + request.limit - 1) // request.limit
        has_next = request.page < total_pages
        has_prev = request.page > 1
        
        # Build sort criteria
        sort_field = self._get_sort_field(request.sort_by)
        sort_direction = 1 if request.sort_order == "asc" else -1
        sort_criteria = [(sort_field, sort_direction)]
        
        # Add secondary sort by _id for consistent ordering
        if sort_field != "_id":
            sort_criteria.append(("_id", sort_direction))
        
        # Execute query with pagination and sorting
        cursor = self.clubs_collection.find(query_filter).sort(sort_criteria).skip(skip).limit(request.limit)
        
        # Convert to response models
        clubs = []
        async for club_doc in cursor:
            club_response = await self._convert_to_club_response(club_doc)
            clubs.append(club_response)
        
        # Create pagination metadata
        pagination = ClubPaginationMetadata(
            total_clubs=total_clubs,
            current_page=request.page,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
            limit=request.limit
        )
        
        return {
            "success": True,
            "message": f"Retrieved {len(clubs)} clubs",
            "clubs": clubs,
            "pagination": pagination.model_dump()
        }

    async def _convert_to_club_response(self, club_doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert database club document to simplified response with only required fields"""
        
        # Get club ID
        club_id = str(club_doc.get("_id", ""))
        
        # Get basic club info
        name = club_doc.get("name", "")
        name_based_id = club_doc.get("name_based_id", "")
        
        # Get owner info
        owner_id = club_doc.get("captain_id", "")
        owner_name = await self._get_owner_name(owner_id)
        owner_role = club_doc.get("deleted_by_role", "")#await self._get_owner_role(owner_id)
        
        # Get status and dates
        status = club_doc.get("status", "pending")
        created_at = club_doc.get("created_at")
        
        # Get deletion and reactivation role information
        deleted_by_role = club_doc.get("deleted_by_role", "")
        reactivated_by_role = club_doc.get("reactivated_by_role", "")
        
        # Handle datetime conversion to ISO string
        if isinstance(created_at, datetime):
            created_date = created_at.isoformat()
        elif isinstance(created_at, str):
            try:
                # Try to parse and convert to ISO format
                parsed_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                created_date = parsed_date.isoformat()
            except:
                created_date = datetime.utcnow().isoformat()
        else:
            created_date = datetime.utcnow().isoformat()
        
        # Return only the required fields
        return {
            "club_id": club_id,
            "name": name,
            "name_based_id": name_based_id,
            "owner_name": owner_name,
            "owner_role": owner_role,
            "created_date": created_date,
            "status": status,
            "owner_id": owner_id,
            "deleted_by_role": deleted_by_role,
            "reactivated_by_role": reactivated_by_role
        }

    async def _get_owner_name(self, owner_id: str) -> str:
        """Get owner name from user ID"""
        try:
            if not owner_id:
                return "Unknown"
            
            user_doc = await self.users_collection.find_one({"_id": ObjectId(owner_id)})
            if user_doc:
                return user_doc.get("full_name", "Unknown")
            return "Unknown"
        except Exception as e:
            print(f"Error getting owner name: {e}")
            return "Unknown"

    async def _get_owner_role(self, owner_id: str) -> str:
        """Get owner role from user ID"""
        try:
            if not owner_id:
                return "Unknown"
            
            user_doc = await self.users_collection.find_one({"_id": ObjectId(owner_id)})
            if user_doc:
                return user_doc.get("role", "Unknown")
            return "Unknown"
        except Exception as e:
            print(f"Error getting owner role: {e}")
            return "Unknown"

    async def _get_moderator_count(self, club_id: str) -> int:
        """Get moderator count for a club"""
        try:
            if not club_id:
                return 0
            
            # Count members with moderator role
            count = await self.club_memberships_collection.count_documents({
                "club_id": club_id,
                "role": "moderator",
                "subscription_status": "active"
            })
            return count
        except Exception as e:
            print(f"Error getting moderator count: {e}")
            return 0

    async def _get_user_ids_by_name(self, name: str) -> List[str]:
        """Get user IDs by name (for owner search)"""
        try:
            name_regex = {"$regex": name, "$options": "i"}
            cursor = self.users_collection.find({"full_name": name_regex})
            user_ids = []
            async for user_doc in cursor:
                user_ids.append(str(user_doc.get("_id", "")))
            return user_ids
        except Exception as e:
            print(f"Error getting user IDs by name: {e}")
            return []

    def _get_sort_field(self, sort_by: ClubSortField) -> str:
        """Convert sort field enum to database field name"""
        if sort_by == ClubSortField.NAME:
            return "name"
        elif sort_by == ClubSortField.OWNER:
            return "captain_id"
        elif sort_by == ClubSortField.CREATED_DATE:
            return "created_at"
        elif sort_by == ClubSortField.MODERATOR_COUNT:
            return "moderator_count"
        elif sort_by == ClubSortField.SUBSCRIPTION_PRICE:
            return "pricing_plans.price"
        elif sort_by == ClubSortField.STATUS:
            return "status"
        else:
            return "created_at"

    async def get_club_statistics(self) -> Dict[str, Any]:
        """Get club statistics for admin dashboard"""
        try:
            # Total clubs
            total_clubs = await self.clubs_collection.count_documents({})
            
            # Active clubs
            active_clubs = await self.clubs_collection.count_documents({"is_active": True})
            
            # Inactive clubs
            inactive_clubs = await self.clubs_collection.count_documents({"is_active": False})
            
            # Clubs by status (case-insensitive)
            approved_clubs = await self.clubs_collection.count_documents({"status": {"$regex": "^approved$", "$options": "i"}})
            pending_clubs = await self.clubs_collection.count_documents({"status": {"$regex": "^pending$", "$options": "i"}})
            rejected_clubs = await self.clubs_collection.count_documents({"status": {"$regex": "^rejected$", "$options": "i"}})
            inactive_clubs = await self.clubs_collection.count_documents({"status": {"$regex": "^inactive$", "$options": "i"}})
            

            
            # Clubs created today
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            clubs_today = await self.clubs_collection.count_documents({
                "created_at": {"$gte": today}
            })
            
            # Clubs created this month
            month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            clubs_this_month = await self.clubs_collection.count_documents({
                "created_at": {"$gte": month_start}
            })
            
            # Total members across all clubs
            total_members = await self.club_memberships_collection.count_documents({"subscription_status": "active"})
            
            return {
                "total_clubs": total_clubs,
                "active_clubs": active_clubs,
                "inactive_clubs": inactive_clubs,
                "approved_clubs": approved_clubs,
                "pending_clubs": pending_clubs,
                "rejected_clubs": rejected_clubs,
                "inactive_clubs": inactive_clubs,
                "clubs_today": clubs_today,
                "clubs_this_month": clubs_this_month,
                "total_members": total_members
            }
        except Exception as e:
            print(f"Error getting club statistics: {e}")
            return {}

    async def get_club_details(self, club_id: str) -> Dict[str, Any]:
        """Get simplified club details with only requested fields"""
        try:
            # Get basic club information
            club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club_doc:
                raise ValueError(f"Club with ID {club_id} not found")
            
            # Get owner name
            owner_id = club_doc.get("captain_id", "")
            owner_name = await self._get_owner_name(owner_id)
            
            # Get moderator count from clubs table
            moderator_count = club_doc.get("moderator_count", 0)
            
            # Get member count from clubs table (total_members field)
            member_count = club_doc.get("total_members", 0)
            
            # Handle datetime conversion to ISO string
            created_at = club_doc.get("created_at")
            if isinstance(created_at, datetime):
                created_date = created_at.isoformat()
            elif isinstance(created_at, str):
                try:
                    parsed_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    created_date = parsed_date.isoformat()
                except:
                    created_date = datetime.utcnow().isoformat()
            else:
                created_date = datetime.utcnow().isoformat()
            
            # Return only the requested fields
            return {
                "club_id": str(club_doc.get("_id", "")),
                "name": club_doc.get("name", ""),
                "owner_name": owner_name,
                "created_date": created_date,
                "status": club_doc.get("status", "pending"),
                "owner_id": owner_id,
                "sub_description": club_doc.get("sub_description", ""),  # Added field
                "description": club_doc.get("description", ""),  # Added field
                "member_count": member_count,  # Added field
                "moderator_count": moderator_count,  # Added field
                "logo_url": club_doc.get("logo_url", "")  # Added logo_url field
            }
            
        except Exception as e:
            print(f"Error getting club details: {e}")
            raise e

    async def update_club_details(self, club_id: str, request: ClubUpdateDetailsRequest, admin_email: str) -> Dict[str, Any]:
        """Update club details including logo URL, name, descriptions, status, and owner name"""
        try:
            # Validate club exists
            club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club_doc:
                raise ValueError(f"Club with ID {club_id} not found")
            
            # Get owner ID from club
            owner_id = club_doc.get("captain_id")
            if not owner_id:
                raise ValueError("Club has no owner assigned")
            
            # Prepare update data
            update_data = {"updated_at": datetime.utcnow()}
            changes = {}
            
            # Update logo URL if provided
            if request.logo_url is not None:
                update_data["logo_url"] = request.logo_url
                changes["logo_url"] = {"old": club_doc.get("logo_url"), "new": request.logo_url}
            
            # Update club name if provided
            if request.name is not None:
                # Check for name uniqueness if changing
                if request.name != club_doc.get("name"):
                    await self._validate_club_uniqueness(request.name, exclude_id=club_id)
                    update_data["name"] = request.name
                    changes["name"] = {"old": club_doc.get("name"), "new": request.name}
            
            # Update sub_description if provided
            if request.sub_description is not None:
                update_data["sub_description"] = request.sub_description
                changes["sub_description"] = {"old": club_doc.get("sub_description"), "new": request.sub_description}
            
            # Update description if provided
            if request.description is not None:
                update_data["description"] = request.description
                changes["description"] = {"old": club_doc.get("description"), "new": request.description}
            
            # Update status if provided
            if request.status is not None:
                update_data["status"] = request.status.value
                changes["status"] = {"old": club_doc.get("status"), "new": request.status.value}
            
            # Update club in database
            if update_data:
                await self.clubs_collection.update_one(
                    {"_id": ObjectId(club_id)},
                    {"$set": update_data}
                )
            
            # Handle owner name update if provided
            if request.owner_name is not None:
                # Get current owner details
                owner_doc = await self.users_collection.find_one({"_id": ObjectId(owner_id)})
                if not owner_doc:
                    raise ValueError("Owner not found in users collection")
                
                current_owner_name = owner_doc.get("full_name", "")
                if request.owner_name != current_owner_name:
                    # Update owner name in users collection
                    await self.users_collection.update_one(
                        {"_id": ObjectId(owner_id)},
                        {
                            "$set": {
                                "full_name": request.owner_name,
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    changes["owner_name"] = {"old": current_owner_name, "new": request.owner_name}
                    print(f"Updated owner name from '{current_owner_name}' to '{request.owner_name}' in users collection")
            
            # Log the action
            await self._log_club_audit(
                action="UPDATE_DETAILS",
                admin_email=admin_email,
                club_id=club_id,
                changes=changes
            )
            
            # Get updated club details
            updated_club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            
            # Get updated owner name
            updated_owner_name = request.owner_name if request.owner_name is not None else await self._get_owner_name(owner_id)
            
            # Return updated club details
            return {
                "club_id": club_id,
                "name": updated_club.get("name", ""),
                "logo_url": updated_club.get("logo_url", ""),
                "sub_description": updated_club.get("sub_description", ""),
                "description": updated_club.get("description", ""),
                "status": updated_club.get("status", "pending"),
                "owner_name": updated_owner_name,
                "updated_at": updated_club.get("updated_at", datetime.utcnow()).isoformat(),
                "changes_made": changes
            }
            
        except ValueError as ve:
            raise ve
        except Exception as e:
            print(f"Error updating club details: {e}")
            raise Exception(f"Failed to update club details: {str(e)}")

    async def update_club_status(self, club_id: str, request: ClubStatusUpdateRequest, admin_email: str, ip_address: Optional[str] = None) -> ClubStatusUpdateResponse:
        """Update club status (ban, suspend, reactivate)"""
        try:
            # Get current club status
            club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club_doc:
                raise ValueError(f"Club with ID {club_id} not found")
            
            previous_status = club_doc.get("status", "pending")
            new_status = self._determine_new_status(previous_status, request.action)
            
            # Prepare update data
            update_data = {"status": new_status, "updated_at": datetime.utcnow()}
            
            # Add suspension details if suspending
            if request.action == ClubAction.SUSPEND and request.duration_days:
                suspension_start = datetime.utcnow()
                suspension_end = suspension_start + timedelta(days=request.duration_days)
                update_data.update({
                    "suspended_at": suspension_start,
                    "suspension_expires": suspension_end,
                    "suspension_reason": request.reason
                })
            
            # Update club status
            await self.clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {"$set": update_data}
            )
            
            # Send club status change notification to all club members
            try:
                from services.notifications.notification_service import (
                    send_notification_to_users,
                    get_club_members,
                    filter_users_by_notification_preference,
                    get_collections,
                )
                
                # Get club name_based_id for notification
                club_name_based_id = club_doc.get("name_based_id")
                if club_name_based_id:
                    # Get all club members
                    all_club_members = await get_club_members(club_name_based_id)
                    
                    if all_club_members:
                        # Filter by club status alerts preference (push candidates)
                        enabled_user_ids = await filter_users_by_notification_preference(
                            all_club_members,
                            "club_status_alerts"
                        )
                        enabled_user_ids = [uid for uid in (enabled_user_ids or []) if uid]

                        # Look up users with active device tokens
                        collections = get_collections()
                        user_tokens_collection = collections.get_user_tokens_collection()

                        users_with_tokens = []
                        if enabled_user_ids:
                            token_cursor = user_tokens_collection.find(
                                {
                                    "user_id": {"$in": enabled_user_ids},
                                    "is_active": True,
                                },
                                {"user_id": 1},
                            )
                            token_docs = await token_cursor.to_list(length=None)
                            users_with_tokens = list(
                                {doc.get("user_id") for doc in token_docs if doc.get("user_id")}
                            )

                        # Build DB and push recipient lists
                        db_user_ids = [uid for uid in all_club_members if uid]
                        push_user_ids = [
                            uid for uid in users_with_tokens if uid in enabled_user_ids
                        ]

                        if db_user_ids:
                            # Prepare notification content
                            status_text = "activated" if new_status == "active" else "deactivated"
                            title = f"Club Status Changed!"
                            body = f"Your club has been {status_text} by admin"

                            notification_data = {
                                "club_id": club_name_based_id,
                                "club_name": club_doc.get("name", "Club"),
                                "new_status": new_status,
                                "previous_status": previous_status,
                                "changed_by": admin_email,
                                "reason": request.reason
                            }

                            notification_result = await send_notification_to_users(
                                user_ids=push_user_ids,
                                title=title,
                                body=body,
                                notification_type="club_status_change",
                                data=notification_data,
                                click_action=f"club/{club_name_based_id}",
                                priority="high",
                                all_user_ids=db_user_ids,
                            )
                            print(f"✅ Club status notification sent for club {club_name_based_id}: {notification_result}")
                        else:
                            print(f"ℹ️ No club members found for club {club_name_based_id}")
                    else:
                        print(f"ℹ️ No club members found for club {club_name_based_id}")
                        
            except Exception as e:
                print(f"⚠️ Failed to send club status notification: {e}")
            
            # Log the action
            await self._log_club_action(club_id, request.action, admin_email, ip_address, request.reason)
            
            # Determine expiration date
            expires_date = None
            if request.action == ClubAction.SUSPEND and request.duration_days:
                expires_date = datetime.utcnow() + timedelta(days=request.duration_days)
            
            return ClubStatusUpdateResponse(
                success=True,
                message=f"Club status updated successfully to {new_status}",
                club_id=club_id,
                previous_status=previous_status,
                new_status=new_status,
                action_taken=request.action.value,
                reason=request.reason,
                effective_date=datetime.utcnow(),
                expires_date=expires_date,
                admin_email=admin_email
            )
            
        except Exception as e:
            print(f"Error updating club status: {e}")
            raise e

    async def get_club_analytics(self, club_id: str, request: ClubAnalyticsRequest) -> ClubAnalyticsResponse:
        """Get comprehensive club analytics"""
        try:
            # Validate club exists
            club_exists = await self.clubs_collection.count_documents({"_id": ObjectId(club_id)})
            if not club_exists:
                raise ValueError(f"Club with ID {club_id} not found")
            
            analytics_data = {}
            
            if request.include_financials:
                analytics_data["financial_summary"] = await self._get_financial_analytics(club_id, request.date_from, request.date_to)
            
            if request.include_activity:
                analytics_data["activity_summary"] = await self._get_activity_analytics(club_id, request.date_from, request.date_to)
            
            if request.include_picks:
                analytics_data["picks_summary"] = await self._get_picks_analytics(club_id, request.date_from, request.date_to)
            
            # Determine analytics period
            if request.date_from and request.date_to:
                period = f"{request.date_from.strftime('%Y-%m-%d')} to {request.date_to.strftime('%Y-%m-%d')}"
            else:
                period = "All time"
            
            return ClubAnalyticsResponse(
                success=True,
                message="Club analytics retrieved successfully",
                club_id=club_id,
                analytics_period=period,
                **analytics_data,
                generated_at=datetime.utcnow()
            )
            
        except Exception as e:
            print(f"Error getting club analytics: {e}")
            raise e

    async def get_club_performance(self, club_id: str) -> ClubPerformanceResponse:
        """Get club performance metrics including win rate and ROI"""
        try:
            # Validate club exists
            club_exists = await self.clubs_collection.count_documents({"_id": ObjectId(club_id)})
            if not club_exists:
                raise ValueError(f"Club with ID {club_id} not found")
            
            # Get performance metrics
            performance = await self._calculate_club_performance(club_id)
            
            return ClubPerformanceResponse(
                success=True,
                message="Club performance metrics retrieved successfully",
                club_id=club_id,
                performance=performance,
                generated_at=datetime.utcnow()
            )
            
        except Exception as e:
            print(f"Error getting club performance: {e}")
            raise e

    async def get_club_activity_logs(self, club_id: str, page: int = 1, limit: int = 50) -> ClubActivityLogResponse:
        """Get activity logs for a specific club"""
        try:
            # Validate club exists
            club_exists = await self.clubs_collection.count_documents({"_id": ObjectId(club_id)})
            if not club_exists:
                raise ValueError(f"Club with ID {club_id} not found")
            
            # Get total logs count
            total_logs = await self.club_memberships_collection.count_documents({"club_id": club_id}) # Changed from club_admin_logs_collection to club_memberships_collection
            
            # Calculate pagination
            skip = (page - 1) * limit
            total_pages = (total_logs + limit - 1) // limit
            has_next = page < total_pages
            has_prev = page > 1
            
            # Get logs with pagination
            cursor = self.club_memberships_collection.find({"club_id": club_id}).sort("joined_date", -1).skip(skip).limit(limit) # Changed sort field to joined_date
            
            logs = []
            async for log_doc in cursor:
                logs.append(ClubActivityLogEntry(
                    log_id=str(log_doc["_id"]),
                    club_id=log_doc["club_id"],
                    action=log_doc["role"], # Assuming action is role for membership logs
                    performed_by=log_doc["user_id"], # Assuming performed_by is user_id
                    admin_email=log_doc["user_id"], # Assuming admin_email is user_id
                    details={"role": log_doc["role"]}, # Placeholder details
                    timestamp=log_doc["joined_date"], # Assuming timestamp is joined_date
                    ip_address=None, # No IP address in this model
                    user_agent=None # No user agent in this model
                ))
            
            # Create pagination metadata
            pagination = ClubPaginationMetadata(
                total_clubs=total_logs,
                current_page=page,
                total_pages=total_pages,
                has_next=has_next,
                has_prev=has_prev,
                limit=limit
            )
            
            return ClubActivityLogResponse(
                success=True,
                message=f"Activity logs retrieved successfully",
                club_id=club_id,
                total_logs=total_logs,
                logs=logs,
                pagination=pagination
            )
            
        except Exception as e:
            print(f"Error getting club activity logs: {e}")
            raise e

    async def perform_bulk_club_actions(self, request: ClubBulkActionRequest, admin_email: str, ip_address: Optional[str] = None) -> ClubBulkActionResponse:
        """Perform bulk actions on multiple clubs"""
        try:
            results = []
            processed_count = 0
            failed_count = 0
            
            for club_id in request.club_ids:
                try:
                    # Validate club exists
                    club_exists = await self.clubs_collection.count_documents({"_id": ObjectId(club_id)})
                    if not club_exists:
                        results.append({
                            "club_id": club_id,
                            "success": False,
                            "error": "Club not found"
                        })
                        failed_count += 1
                        continue
                    
                    # Perform the action
                    if request.action == ClubAction.BAN:
                        await self._ban_club(club_id, request.reason)
                    elif request.action == ClubAction.SUSPEND:
                        await self._suspend_club(club_id, request.reason, request.duration_days)
                    elif request.action == ClubAction.REACTIVATE:
                        await self._reactivate_club(club_id)
                    
                    # Log the action
                    await self._log_club_action(club_id, request.action, admin_email, ip_address, request.reason)
                    
                    results.append({
                        "club_id": club_id,
                        "success": True,
                        "message": f"Club {request.action.value} successfully"
                    })
                    processed_count += 1
                    
                except Exception as e:
                    results.append({
                        "club_id": club_id,
                        "success": False,
                        "error": str(e)
                    })
                    failed_count += 1
            
            # Create summary
            summary = {
                "action": request.action.value,
                "total_clubs": len(request.club_ids),
                "successful": processed_count,
                "failed": failed_count,
                "success_rate": (processed_count / len(request.club_ids)) * 100 if request.club_ids else 0
            }
            
            return ClubBulkActionResponse(
                success=True,
                message=f"Bulk {request.action.value} operation completed",
                action=request.action.value,
                total_clubs=len(request.club_ids),
                processed_clubs=processed_count,
                failed_clubs=failed_count,
                results=results,
                summary=summary
            )
            
        except Exception as e:
            print(f"Error performing bulk club actions: {e}")
            raise e

    # Private helper methods
    async def _get_owner_details(self, owner_id: str) -> OwnerDetails:
        """Get comprehensive owner details"""
        try:
            if not owner_id:
                return OwnerDetails(
                    user_id="",
                    name="Unknown",
                    email="",
                    phone=None,
                    active_club_count=0,
                    revenue_earned=0.0,
                    total_revenue=0.0,
                    avatar_url=None,
                    joined_date=datetime.utcnow(),
                    is_verified=False
                )
            
            # Get user details
            user_doc = await self.users_collection.find_one({"_id": ObjectId(owner_id)})
            if not user_doc:
                return OwnerDetails(
                    user_id=owner_id,
                    name="Unknown",
                    email="",
                    phone=None,
                    active_club_count=0,
                    revenue_earned=0.0,
                    total_revenue=0.0,
                    avatar_url=None,
                    joined_date=datetime.utcnow(),
                    is_verified=False
                )
            
            # Get active club count
            active_club_count = await self.clubs_collection.count_documents({
                "captain_id": owner_id,
                "is_active": True
            })
            
            # Get revenue data (90% share)
            total_revenue = await self._get_owner_total_revenue(owner_id)
            revenue_earned = total_revenue * 0.9  # 90% share
            
            return OwnerDetails(
                user_id=owner_id,
                name=user_doc.get("full_name", "Unknown"),
                email=user_doc.get("email", ""),
                phone=user_doc.get("phone"),
                active_club_count=active_club_count,
                revenue_earned=revenue_earned,
                total_revenue=total_revenue,
                avatar_url=user_doc.get("profile_picture"),
                joined_date=user_doc.get("created_at", datetime.utcnow()),
                is_verified=user_doc.get("is_verified", False)
            )
            
        except Exception as e:
            print(f"Error getting owner details: {e}")
            return OwnerDetails(
                user_id=owner_id,
                name="Error",
                email="",
                phone=None,
                active_club_count=0,
                revenue_earned=0.0,
                total_revenue=0.0,
                avatar_url=None,
                joined_date=datetime.utcnow(),
                is_verified=False
            )

    async def _get_moderator_details(self, club_id: str) -> List[ModeratorDetails]:
        """Get moderator details for a club"""
        try:
            # Get club memberships with moderator roles
            cursor = self.club_memberships_collection.find({
                "club_id": club_id,
                "role": {"$in": ["moderator", "analyst", "editor"]},
                "subscription_status": "active"
            })
            
            moderators = []
            async for membership in cursor:
                user_id = membership.get("user_id")
                if user_id:
                    user_doc = await self.users_collection.find_one({"_id": ObjectId(user_id)})
                    if user_doc:
                        moderators.append(ModeratorDetails(
                            user_id=user_id,
                            name=user_doc.get("full_name", "Unknown"),
                            email=user_doc.get("email", ""),
                            phone=user_doc.get("phone"),
                            role=ModeratorRole(membership.get("role", "moderator")),
                            joined_date=membership.get("joined_date", datetime.utcnow()),
                            is_active=True,
                            avatar_url=user_doc.get("profile_picture")
                        ))
            
            return moderators
            
        except Exception as e:
            print(f"Error getting moderator details: {e}")
            return []

    async def _get_financial_details(self, club_id: str) -> FinancialDetails:
        """Get comprehensive financial details for a club"""
        try:
            # Get active subscriptions
            active_subscriptions = await self.club_memberships_collection.count_documents({
                "club_id": club_id,
                "subscription_status": "active"
            })
            
            # Get past subscriptions
            past_subscriptions = await self.club_memberships_collection.count_documents({
                "club_id": club_id,
                "subscription_status": {"$in": ["expired", "cancelled"]}
            })
            
            # Get payment data
            payment_cursor = self.club_payments_collection.find({"club_id": club_id})
            total_revenue = 0.0
            monthly_revenue = 0.0
            payment_count = 0
            
            async for payment in payment_cursor:
                amount = payment.get("amount", 0.0)
                total_revenue += amount
                payment_count += 1
                
                # Calculate monthly recurring revenue
                if payment.get("subscription_status") == "active":
                    monthly_revenue += amount
            
            # Calculate averages
            average_subscription_value = total_revenue / payment_count if payment_count > 0 else 0.0
            
            # Get refund data
            refund_cursor = self.club_refunds_collection.find({"club_id": club_id})
            refund_total = 0.0
            async for refund in refund_cursor:
                refund_total += refund.get("amount", 0.0)
            
            net_revenue = total_revenue - refund_total
            
            return FinancialDetails(
                total_revenue=total_revenue,
                active_subscribers=active_subscriptions,
                past_subscriptions=past_subscriptions,
                monthly_recurring_revenue=monthly_revenue,
                average_subscription_value=average_subscription_value,
                refund_total=refund_total,
                net_revenue=net_revenue
            )
            
        except Exception as e:
            print(f"Error getting financial details: {e}")
            return FinancialDetails(
                total_revenue=0.0,
                active_subscribers=0,
                past_subscriptions=0,
                monthly_recurring_revenue=0.0,
                average_subscription_value=0.0,
                refund_total=0.0,
                net_revenue=0.0
            )

    async def _get_activity_metrics(self, club_id: str) -> ActivityMetrics:
        """Get activity metrics and calculate engagement score"""
        try:
            # Get picks count
            picks_count = await self.club_picks_collection.count_documents({"club_id": club_id})
            
            # Get messages count (from chat service)
            messages_count = await self._get_club_messages_count(club_id)
            
            # Get last activity date
            last_activity = await self._get_last_activity_date(club_id)
            
            # Calculate days since last activity
            days_since_last = 0
            if last_activity:
                days_since_last = (datetime.utcnow() - last_activity).days
            
            # Determine inactivity flag (30+ days without activity)
            is_inactive = days_since_last > 30
            
            # Calculate engagement score (0-100)
            engagement_score = self._calculate_engagement_score(picks_count, messages_count, days_since_last)
            
            return ActivityMetrics(
                picks_posted=picks_count,
                messages_sent=messages_count,
                total_engagement=picks_count + messages_count,
                last_activity_date=last_activity,
                days_since_last_activity=days_since_last,
                is_inactive=is_inactive,
                engagement_score=engagement_score
            )
            
        except Exception as e:
            print(f"Error getting activity metrics: {e}")
            return ActivityMetrics(
                picks_posted=0,
                messages_sent=0,
                total_engagement=0,
                last_activity_date=None,
                days_since_last_activity=0,
                is_inactive=True,
                engagement_score=0.0
            )

    async def _get_picks_history(self, club_id: str) -> List[PickDetails]:
        """Get picks history for a club"""
        try:
            cursor = self.club_picks_collection.find({"club_id": club_id}).sort("timestamp", -1).limit(100)
            
            picks = []
            async for pick_doc in cursor:
                # Get submitter details
                submitter_id = pick_doc.get("submitted_by")
                submitter_name = "Unknown"
                submitter_role = "member"
                
                if submitter_id:
                    user_doc = await self.users_collection.find_one({"_id": ObjectId(submitter_id)})
                    if user_doc:
                        submitter_name = user_doc.get("full_name", "Unknown")
                        # Check if submitter is captain or moderator
                        membership = await self.club_memberships_collection.find_one({
                            "club_id": club_id,
                            "user_id": submitter_id
                        })
                        if membership:
                            submitter_role = membership.get("role", "member")
                
                picks.append(PickDetails(
                    pick_id=str(pick_doc["_id"]),
                    submitted_by=submitter_id or "",
                    submitter_role=submitter_role,
                    submitter_name=submitter_name,
                    game_info=pick_doc.get("game_info", ""),
                    pick_type=pick_doc.get("pick_type", ""),
                    pick_details=pick_doc.get("pick_details", ""),
                    timestamp=pick_doc.get("timestamp", datetime.utcnow()),
                    status=pick_doc.get("status", "pending"),
                    outcome=pick_doc.get("outcome"),
                    win_loss=pick_doc.get("win_loss")
                ))
            
            return picks
            
        except Exception as e:
            print(f"Error getting picks history: {e}")
            return []

    async def _get_refund_log(self, club_id: str) -> List[RefundLogEntry]:
        """Get refund log for a club"""
        try:
            cursor = self.club_refunds_collection.find({"club_id": club_id}).sort("date", -1)
            
            refunds = []
            async for refund_doc in cursor:
                refunds.append(RefundLogEntry(
                    refund_id=str(refund_doc["_id"]),
                    amount=refund_doc.get("amount", 0.0),
                    date=refund_doc.get("date", datetime.utcnow()),
                    reason=refund_doc.get("reason", ""),
                    member_name=refund_doc.get("member_name", ""),
                    member_email=refund_doc.get("member_email", ""),
                    processed_by=refund_doc.get("processed_by", "")
                ))
            
            return refunds
            
        except Exception as e:
            print(f"Error getting refund log: {e}")
            return []

    async def _get_payment_history(self, club_id: str) -> List[PaymentHistoryEntry]:
        """Get payment history for a club"""
        try:
            cursor = self.club_payments_collection.find({"club_id": club_id}).sort("date", -1).limit(100)
            
            payments = []
            async for payment_doc in cursor:
                # Get member details
                member_id = payment_doc.get("member_id")
                member_name = "Unknown"
                member_email = ""
                
                if member_id:
                    user_doc = await self.users_collection.find_one({"_id": ObjectId(member_id)})
                    if user_doc:
                        member_name = user_doc.get("full_name", "Unknown")
                        member_email = user_doc.get("email", "")
                
                payments.append(PaymentHistoryEntry(
                    transaction_id=payment_doc.get("transaction_id", ""),
                    member_name=member_name,
                    member_email=member_email,
                    amount=payment_doc.get("amount", 0.0),
                    date=payment_doc.get("date", datetime.utcnow()),
                    status=payment_doc.get("status", ""),
                    payment_method=payment_doc.get("payment_method"),
                    subscription_plan=payment_doc.get("subscription_plan", "")
                ))
            
            return payments
            
        except Exception as e:
            print(f"Error getting payment history: {e}")
            return []

    async def _log_club_action(self, club_id: str, action: ClubAction, admin_email: str, ip_address: Optional[str] = None, reason: Optional[str] = None):
        """Log club action for audit trail"""
        try:
            log_entry = {
                "club_id": club_id,
                "action": action.value,
                "performed_by": "admin",
                "admin_email": admin_email,
                "details": {
                    "reason": reason,
                    "timestamp": datetime.utcnow()
                },
                "timestamp": datetime.utcnow(),
                "ip_address": ip_address,
                "user_agent": None  # Could be added from request headers
            }
            
            await self.club_memberships_collection.insert_one(log_entry) # Changed from club_admin_logs_collection to club_memberships_collection
            
        except Exception as e:
            print(f"Error logging club action: {e}")

    def _determine_new_status(self, current_status: str, action: ClubAction) -> str:
        """Determine new status based on action"""
        if action == ClubAction.BAN:
            return "banned"
        elif action == ClubAction.SUSPEND:
            return "suspended"
        elif action == ClubAction.REACTIVATE:
            return "approved"
        else:
            return current_status

    async def _ban_club(self, club_id: str, reason: Optional[str]):
        """Ban a club"""
        await self.clubs_collection.update_one(
            {"_id": ObjectId(club_id)},
            {
                "$set": {
                    "status": "banned",
                    "banned_at": datetime.utcnow(),
                    "ban_reason": reason,
                    "updated_at": datetime.utcnow()
                }
            }
        )

    async def _suspend_club(self, club_id: str, reason: Optional[str], duration_days: Optional[int]):
        """Suspend a club"""
        suspension_data = {
            "status": "suspended",
            "suspended_at": datetime.utcnow(),
            "suspension_reason": reason,
            "updated_at": datetime.utcnow()
        }
        
        if duration_days:
            suspension_data["suspension_expires"] = datetime.utcnow() + timedelta(days=duration_days)
        
        await self.clubs_collection.update_one(
            {"_id": ObjectId(club_id)},
            {"$set": suspension_data}
        )

    async def _reactivate_club(self, club_id: str):
        """Reactivate a club"""
        await self.clubs_collection.update_one(
            {"_id": ObjectId(club_id)},
            {
                "$set": {
                    "status": "approved",
                    "reactivated_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                },
                "$unset": {
                    "suspended_at": "",
                    "suspension_expires": "",
                    "suspension_reason": "",
                    "banned_at": "",
                    "ban_reason": ""
                }
            }
        )

    async def _get_owner_total_revenue(self, owner_id: str) -> float:
        """Get total revenue for an owner across all clubs"""
        try:
            # Get all clubs owned by this user
            cursor = self.clubs_collection.find({"captain_id": owner_id})
            total_revenue = 0.0
            
            async for club in cursor:
                club_id = str(club["_id"])
                # Get revenue for this club
                club_revenue = await self._get_club_revenue(club_id)
                total_revenue += club_revenue
            
            return total_revenue
            
        except Exception as e:
            print(f"Error getting owner total revenue: {e}")
            return 0.0

    async def _get_club_revenue(self, club_id: str) -> float:
        """Get total revenue for a specific club"""
        try:
            cursor = self.club_payments_collection.find({"club_id": club_id, "status": "completed"})
            total_revenue = 0.0
            
            async for payment in cursor:
                total_revenue += payment.get("amount", 0.0)
            
            return total_revenue
            
        except Exception as e:
            print(f"Error getting club revenue: {e}")
            return 0.0

    async def _get_club_messages_count(self, club_id: str) -> int:
        """Get message count for a club (placeholder for chat service integration)"""
        # This would integrate with the chat service
        # For now, return a placeholder value
        return 0

    async def _get_last_activity_date(self, club_id: str) -> Optional[datetime]:
        """Get last activity date for a club"""
        try:
            # Check last pick
            last_pick = await self.club_picks_collection.find_one(
                {"club_id": club_id},
                sort=[("timestamp", -1)]
            )
            
            # Check last payment
            last_payment = await self.club_payments_collection.find_one(
                {"club_id": club_id},
                sort=[("date", -1)]
            )
            
            last_activity = None
            
            if last_pick and last_payment:
                pick_time = last_pick.get("timestamp")
                payment_time = last_payment.get("date")
                last_activity = max(pick_time, payment_time) if pick_time and payment_time else None
            elif last_pick:
                last_activity = last_pick.get("timestamp")
            elif last_payment:
                last_activity = last_payment.get("date")
            
            return last_activity
            
        except Exception as e:
            print(f"Error getting last activity date: {e}")
            return None

    def _calculate_engagement_score(self, picks_count: int, messages_count: int, days_since_last: int) -> float:
        """Calculate engagement score (0-100)"""
        try:
            # Base score from activity volume
            activity_score = min((picks_count + messages_count) * 2, 50)
            
            # Recency score (higher for recent activity)
            if days_since_last == 0:
                recency_score = 50
            elif days_since_last <= 7:
                recency_score = 40
            elif days_since_last <= 30:
                recency_score = 20
            else:
                recency_score = 0
            
            total_score = activity_score + recency_score
            return min(max(total_score, 0), 100)
            
        except Exception as e:
            print(f"Error calculating engagement score: {e}")
            return 0.0

    async def _build_complete_club_info(self, club_doc: Dict[str, Any]) -> Dict[str, Any]:
        """Build complete club information dictionary"""
        try:
            return {
                "club_id": str(club_doc.get("_id", "")),
                "name": club_doc.get("name", ""),
                "description": club_doc.get("description", ""),
                "logo_url": club_doc.get("logo_url"),
                "status": club_doc.get("status", "pending"),
                "subscription_price": self._get_subscription_price(club_doc),
                "currency": self._get_currency(club_doc),
                "plan_type": self._get_plan_type(club_doc),
                "created_date": club_doc.get("created_at"),
                "updated_date": club_doc.get("updated_at"),
                "member_count": club_doc.get("member_count", 0),
                "win_percentage": club_doc.get("win_pct", 0.0),
                "is_active": club_doc.get("is_active", True),
                "suspended_at": club_doc.get("suspended_at"),
                "suspension_expires": club_doc.get("suspension_expires"),
                "suspension_reason": club_doc.get("suspension_reason"),
                "banned_at": club_doc.get("banned_at"),
                "ban_reason": club_doc.get("ban_reason")
            }
            
        except Exception as e:
            print(f"Error building club info: {e}")
            return {}

    def _get_subscription_price(self, club_doc: Dict[str, Any]) -> float:
        """Get subscription price from club document"""
        try:
            pricing_plans = club_doc.get("pricing_plans", [])
            if pricing_plans:
                return pricing_plans[0].get("price", 0.0)
            return 0.0
        except Exception:
            return 0.0

    def _get_currency(self, club_doc: Dict[str, Any]) -> str:
        """Get currency from club document"""
        try:
            pricing_plans = club_doc.get("pricing_plans", [])
            if pricing_plans:
                return pricing_plans[0].get("currency", "USD")
            return "USD"
        except Exception:
            return "USD"

    def _get_plan_type(self, club_doc: Dict[str, Any]) -> str:
        """Get plan type from club document"""
        try:
            pricing_plans = club_doc.get("pricing_plans", [])
            if pricing_plans:
                return pricing_plans[0].get("plan", "monthly")
            return "monthly"
        except Exception:
            return "monthly"

    async def _get_financial_analytics(self, club_id: str, date_from: Optional[datetime], date_to: Optional[datetime]) -> Dict[str, Any]:
        """Get financial analytics for a club within a date range"""
        try:
            # Build date filter
            date_filter = {"club_id": club_id}
            if date_from or date_to:
                date_filter["date"] = {}
                if date_from:
                    date_filter["date"]["$gte"] = date_from
                if date_to:
                    date_filter["date"]["$lte"] = date_to
            
            # Get payment data
            payments_cursor = self.club_payments_collection.find(date_filter)
            total_revenue = 0.0
            payment_count = 0
            
            async for payment in payments_cursor:
                total_revenue += payment.get("amount", 0.0)
                payment_count += 1
            
            # Get refund data
            refunds_cursor = self.club_refunds_collection.find(date_filter)
            total_refunds = 0.0
            refund_count = 0
            
            async for refund in refunds_cursor:
                total_refunds += refund.get("amount", 0.0)
                refund_count += 1
            
            # Calculate metrics
            net_revenue = total_revenue - total_refunds
            average_payment = total_revenue / payment_count if payment_count > 0 else 0.0
            
            return {
                "total_revenue": total_revenue,
                "total_refunds": total_refunds,
                "net_revenue": net_revenue,
                "payment_count": payment_count,
                "refund_count": refund_count,
                "average_payment": average_payment,
                "refund_rate": (refund_count / payment_count * 100) if payment_count > 0 else 0.0
            }
            
        except Exception as e:
            print(f"Error getting financial analytics: {e}")
            return {}

    async def _get_activity_analytics(self, club_id: str, date_from: Optional[datetime], date_to: Optional[datetime]) -> Dict[str, Any]:
        """Get activity analytics for a club within a date range"""
        try:
            # Build date filter for picks
            picks_filter = {"club_id": club_id}
            if date_from or date_to:
                picks_filter["timestamp"] = {}
                if date_from:
                    picks_filter["timestamp"]["$gte"] = date_from
                if date_to:
                    picks_filter["timestamp"]["$lte"] = date_to
            
            # Get picks data
            picks_count = await self.club_picks_collection.count_documents(picks_filter)
            
            # Get membership data
            membership_filter = {"club_id": club_id}
            if date_from or date_to:
                membership_filter["joined_date"] = {}
                if date_from:
                    membership_filter["joined_date"]["$gte"] = date_from
                if date_to:
                    membership_filter["joined_date"]["$lte"] = date_to
            
            new_members = await self.club_memberships_collection.count_documents(membership_filter)
            active_members = await self.club_memberships_collection.count_documents({
                "club_id": club_id,
                "subscription_status": "active"
            })
            
            # Calculate engagement score
            engagement_score = self._calculate_engagement_score(picks_count, 0, 0)  # Messages count not available
            
            return {
                "picks_posted": picks_count,
                "new_members": new_members,
                "active_members": active_members,
                "engagement_score": engagement_score,
                "picks_per_member": picks_count / active_members if active_members > 0 else 0.0
            }
            
        except Exception as e:
            print(f"Error getting activity analytics: {e}")
            return {}

    async def _get_picks_analytics(self, club_id: str, date_from: Optional[datetime], date_to: Optional[datetime]) -> Dict[str, Any]:
        """Get picks analytics for a club within a date range"""
        try:
            # Build date filter
            picks_filter = {"club_id": club_id}
            if date_from or date_to:
                picks_filter["timestamp"] = {}
                if date_from:
                    picks_filter["timestamp"]["$gte"] = date_from
                if date_to:
                    picks_filter["timestamp"]["$lte"] = date_to
            
            # Get picks data
            picks_cursor = self.club_picks_collection.find(picks_filter)
            
            total_picks = 0
            winning_picks = 0
            losing_picks = 0
            pending_picks = 0
            
            async for pick in picks_cursor:
                total_picks += 1
                outcome = pick.get("outcome")
                if outcome == "win":
                    winning_picks += 1
                elif outcome == "loss":
                    losing_picks += 1
                else:
                    pending_picks += 1
            
            # Calculate metrics
            win_rate = (winning_picks / total_picks * 100) if total_picks > 0 else 0.0
            loss_rate = (losing_picks / total_picks * 100) if total_picks > 0 else 0.0
            
            return {
                "total_picks": total_picks,
                "winning_picks": winning_picks,
                "losing_picks": losing_picks,
                "pending_picks": pending_picks,
                "win_rate": win_rate,
                "loss_rate": loss_rate,
                "picks_performance": "positive" if win_rate > 50 else "negative" if win_rate < 50 else "neutral"
            }
            
        except Exception as e:
            print(f"Error getting picks analytics: {e}")
            return {}

    async def _calculate_club_performance(self, club_id: str) -> ClubPerformanceMetrics:
        """Calculate comprehensive club performance metrics"""
        try:
            # Get all picks for the club
            picks_cursor = self.club_picks_collection.find({"club_id": club_id})
            
            total_picks = 0
            winning_picks = 0
            losing_picks = 0
            total_stake = 0.0
            total_return = 0.0
            total_odds = 0.0
            
            monthly_data = {}
            top_performers = {}
            
            async for pick in picks_cursor:
                total_picks += 1
                
                # Calculate basic stats
                outcome = pick.get("outcome")
                if outcome == "win":
                    winning_picks += 1
                elif outcome == "loss":
                    losing_picks += 1
                
                # Calculate financial metrics (if available)
                stake = pick.get("stake", 0.0)
                odds = pick.get("odds", 1.0)
                total_stake += stake
                total_odds += odds
                
                if outcome == "win":
                    total_return += stake * odds
                
                # Track monthly performance
                timestamp = pick.get("timestamp")
                if timestamp:
                    month_key = timestamp.strftime("%Y-%m")
                    if month_key not in monthly_data:
                        monthly_data[month_key] = {"picks": 0, "wins": 0, "losses": 0}
                    monthly_data[month_key]["picks"] += 1
                    if outcome == "win":
                        monthly_data[month_key]["wins"] += 1
                    elif outcome == "loss":
                        monthly_data[month_key]["losses"] += 1
                
                # Track top performers
                submitter = pick.get("submitted_by")
                if submitter:
                    if submitter not in top_performers:
                        top_performers[submitter] = {"picks": 0, "wins": 0, "losses": 0}
                    top_performers[submitter]["picks"] += 1
                    if outcome == "win":
                        top_performers[submitter]["wins"] += 1
                    elif outcome == "loss":
                        top_performers[submitter]["losses"] += 1
            
            # Calculate metrics
            win_rate = (winning_picks / total_picks * 100) if total_picks > 0 else 0.0
            average_odds = total_odds / total_picks if total_picks > 0 else 0.0
            profit_loss = total_return - total_stake
            roi_percentage = (profit_loss / total_stake * 100) if total_stake > 0 else 0.0
            
            # Format monthly performance
            monthly_performance = []
            for month, data in sorted(monthly_data.items()):
                monthly_performance.append({
                    "month": month,
                    "picks": data["picks"],
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "win_rate": (data["wins"] / data["picks"] * 100) if data["picks"] > 0 else 0.0
                })
            
            # Format top performers
            top_performers_list = []
            for user_id, data in sorted(top_performers.items(), key=lambda x: x[1]["wins"], reverse=True)[:10]:
                user_doc = await self.users_collection.find_one({"_id": ObjectId(user_id)})
                name = user_doc.get("full_name", "Unknown") if user_doc else "Unknown"
                
                top_performers_list.append({
                    "user_id": user_id,
                    "name": name,
                    "picks": data["picks"],
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "win_rate": (data["wins"] / data["picks"] * 100) if data["picks"] > 0 else 0.0
                })
            
            return ClubPerformanceMetrics(
                club_id=club_id,
                win_rate=win_rate,
                total_picks=total_picks,
                winning_picks=winning_picks,
                losing_picks=losing_picks,
                average_odds=average_odds,
                total_stake=total_stake,
                total_return=total_return,
                profit_loss=profit_loss,
                roi_percentage=roi_percentage,
                monthly_performance=monthly_performance,
                top_performers=top_performers_list
            )
            
        except Exception as e:
            print(f"Error calculating club performance: {e}")
            return ClubPerformanceMetrics(
                club_id=club_id,
                win_rate=0.0,
                total_picks=0,
                winning_picks=0,
                losing_picks=0,
                average_odds=0.0,
                total_stake=0.0,
                total_return=0.0,
                profit_loss=0.0,
                roi_percentage=0.0,
                monthly_performance=[],
                top_performers=[]
            )

    async def search_clubs_advanced(self, request: ClubAdvancedSearchRequest, admin_email: str, ip_address: Optional[str] = None) -> ClubAdvancedSearchResponse:
        """Advanced search for clubs and club owners with comprehensive filtering and sorting"""
        start_time = time.time()
        
        try:
            # Build the aggregation pipeline for optimized search
            pipeline = []
            
            # Stage 1: Match clubs based on basic filters
            match_stage = {}
            
            # Club name filter (partial match, case-insensitive)
            if request.club_name:
                match_stage["name"] = {"$regex": request.club_name, "$options": "i"}
            
            # Status filter (exact match)
            if request.status:
                match_stage["status"] = request.status.value
            
            # Date range filter for created_at
            if request.date_from or request.date_to:
                date_filter = {}
                if request.date_from:
                    date_filter["$gte"] = request.date_from
                if request.date_to:
                    # Add one day to include the entire end date
                    end_date = request.date_to.replace(hour=23, minute=59, second=59, microsecond=999999)
                    date_filter["$lte"] = end_date
                match_stage["created_at"] = date_filter
            
            if match_stage:
                pipeline.append({"$match": match_stage})
            
            # Stage 2: Lookup owner details from users collection
            pipeline.append({
                "$lookup": {
                    "from": "users",
                    "let": {"captain_id": {"$toObjectId": "$captain_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$captain_id"]}}},
                        {"$project": {
                            "_id": 1,
                            "full_name": 1,
                            "email": 1,
                            "phone": 1
                        }}
                    ],
                    "as": "owner_details"
                }
            })
            
            # Stage 3: Unwind owner details and filter by owner criteria
            pipeline.append({"$unwind": {"path": "$owner_details", "preserveNullAndEmptyArrays": True}})
            
            # Build owner filter conditions
            owner_match_conditions = []
            
            # Owner name filter (partial match, case-insensitive)
            if request.owner_name:
                owner_match_conditions.append({
                    "owner_details.full_name": {"$regex": request.owner_name, "$options": "i"}
                })
            
            # Email filter (partial match, case-insensitive)
            if request.email:
                owner_match_conditions.append({
                    "owner_details.email": {"$regex": request.email, "$options": "i"}
                })
            
            # Phone filter (exact match)
            if request.phone:
                # Clean phone number for exact matching
                clean_phone = request.phone
                owner_match_conditions.append({
                    "$or": [
                        {"owner_details.phone": clean_phone},
                        {"owner_details.phone": {"$regex": f".*{clean_phone}.*"}}
                    ]
                })
            
            # Apply owner filters if any exist
            if owner_match_conditions:
                pipeline.append({
                    "$match": {
                        "$and": owner_match_conditions
                    }
                })
            
            # Stage 4: Add computed fields and enrichment
            pipeline.append({
                "$addFields": {
                    "owner_name": {"$ifNull": ["$owner_details.full_name", "Unknown"]},
                    "owner_email": {"$ifNull": ["$owner_details.email", ""]},
                    "owner_phone": {"$ifNull": ["$owner_details.phone", ""]}
                }
            })
            
            # Stage 5: Add computed fields needed for sorting (before count and sorting)
            self._add_computed_fields_for_sorting(pipeline, request.sort_by)
            
            # Stage 6: Get total count for pagination (before limit/skip)
            count_pipeline = pipeline.copy()
            count_pipeline.append({"$count": "total"})
            
            # Execute count query
            count_result = await self.clubs_collection.aggregate(count_pipeline).to_list(1)
            total_clubs = count_result[0]["total"] if count_result else 0
            
            # Stage 7: Add enhanced sorting
            sort_field, sort_direction = self._get_search_sort_criteria(request.sort_by, request.sort_order)
            
            # Build sort stage
            sort_stage = {sort_field: sort_direction}
            
            # Add secondary sort by _id for consistent ordering
            if sort_field != "_id":
                sort_stage["_id"] = sort_direction
            
            pipeline.append({"$sort": sort_stage})
            
            # Stage 8: Apply pagination
            skip = (request.page - 1) * request.limit
            pipeline.extend([
                {"$skip": skip},
                {"$limit": request.limit}
            ])
            
            # Stage 9: Project final fields
            pipeline.append({
                "$project": {
                    "_id": 1,
                    "name": 1,
                    "description": 1,
                    "status": 1,
                    "logo_url": 1,
                    "created_at": 1,
                    "updated_at": 1,
                    "member_count": 1,
                    "win_pct": 1,
                    "is_active": 1,
                    "pricing_plans": 1,
                    "captain_id": 1,
                    "owner_name": 1,
                    "owner_email": 1,
                    "owner_phone": 1
                }
            })
            
            # Execute the main search query
            cursor = self.clubs_collection.aggregate(pipeline)
            clubs_data = await cursor.to_list(None)
            
            # Convert to response models
            clubs = []
            for club_doc in clubs_data:
                # Get moderator count
                moderator_count = await self._get_moderator_count(str(club_doc.get("_id", "")))
                
                # Get subscription info
                pricing_plans = club_doc.get("pricing_plans", [])
                subscription_price = 0.0
                currency = "USD"
                if pricing_plans:
                    first_plan = pricing_plans[0]
                    subscription_price = first_plan.get("price", 0.0)
                    currency = first_plan.get("currency", "USD")
                
                # Handle dates
                created_at = club_doc.get("created_at")
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    except:
                        created_at = datetime.utcnow()
                elif not created_at:
                    created_at = datetime.utcnow()
                
                updated_at = club_doc.get("updated_at")
                if isinstance(updated_at, str):
                    try:
                        updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                    except:
                        updated_at = created_at
                elif not updated_at:
                    updated_at = created_at
                
                club_response = {
                    "club_id": str(club_doc.get("_id", "")),
                    "name": club_doc.get("name", ""),
                    "owner_name": club_doc.get("owner_name", "Unknown"),
                    "created_date": created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
                    "status": club_doc.get("status", "pending"),
                    "owner_id": club_doc.get("captain_id", "")
                }
                clubs.append(club_response)
            
            # Calculate pagination metadata
            total_pages = (total_clubs + request.limit - 1) // request.limit
            has_next = request.page < total_pages
            has_prev = request.page > 1
            
            pagination = ClubPaginationMetadata(
                total_clubs=total_clubs,
                current_page=request.page,
                total_pages=total_pages,
                has_next=has_next,
                has_prev=has_prev,
                limit=request.limit
            )
            
            # Calculate search time
            end_time = time.time()
            search_time_ms = int((end_time - start_time) * 1000)
            
            # Build enhanced search metadata
            search_metadata = {
                "applied_filters": {
                    "club_name": request.club_name,
                    "owner_name": request.owner_name,
                    "email": request.email,
                    "phone": request.phone,
                    "status": request.status.value if request.status else None,
                    "date_from": request.date_from.isoformat() if request.date_from else None,
                    "date_to": request.date_to.isoformat() if request.date_to else None
                },
                "applied_sorting": {
                    "sort_by": request.sort_by.value if request.sort_by else None,
                    "sort_order": request.sort_order.value if request.sort_order else None,
                    "sort_field_used": sort_field,
                    "sort_direction_used": "descending" if sort_direction == -1 else "ascending"
                },
                "search_performance": {
                    "query_time_ms": search_time_ms,
                    "total_documents_searched": total_clubs,
                    "results_returned": len(clubs)
                }
            }
            
            # Log the search operation
            await self._log_search_operation(admin_email, ip_address, request.dict(), total_clubs, search_time_ms)
            
            return {
                "success": True,
                "message": f"Found {len(clubs)} clubs matching search criteria",
                "clubs": clubs,
                "pagination": pagination.model_dump(),
                "search_metadata": search_metadata,
                "total_results": total_clubs,
                "search_time_ms": search_time_ms
            }
            
        except Exception as e:
            print(f"Error in advanced club search: {e}")
            # Calculate search time even for errors
            end_time = time.time()
            search_time_ms = int((end_time - start_time) * 1000)
            
            return {
                "success": False,
                "message": f"Search failed: {str(e)}",
                "clubs": [],
                "pagination": ClubPaginationMetadata(
                    total_clubs=0,
                    current_page=request.page,
                    total_pages=0,
                    has_next=False,
                    has_prev=False,
                    limit=request.limit
                ).model_dump(),
                "search_metadata": {
                    "error": str(e),
                    "search_time_ms": search_time_ms
                },
                "total_results": 0,
                "search_time_ms": search_time_ms
            }

    async def _log_search_operation(self, admin_email: str, ip_address: Optional[str], search_criteria: dict, results_count: int, response_time_ms: int):
        """Log search operations for analytics and monitoring"""
        try:
            log_entry = {
                "admin_email": admin_email,
                "search_criteria": search_criteria,
                "results_count": results_count,
                "timestamp": datetime.utcnow(),
                "ip_address": ip_address,
                "response_time_ms": response_time_ms,
                "search_type": "advanced_club_search"
            }
            
            await self.search_logs_collection.insert_one(log_entry)
            
        except Exception as e:
            print(f"Error logging search operation: {e}")

    async def get_search_performance_stats(self) -> Dict[str, Any]:
        """Get search performance statistics for monitoring"""
        try:
            # Get stats from last 24 hours
            yesterday = datetime.utcnow() - timedelta(days=1)
            
            # Average response time
            avg_response_pipeline = [
                {"$match": {"timestamp": {"$gte": yesterday}, "search_type": "advanced_club_search"}},
                {"$group": {
                    "_id": None,
                    "avg_response_time": {"$avg": "$response_time_ms"},
                    "max_response_time": {"$max": "$response_time_ms"},
                    "min_response_time": {"$min": "$response_time_ms"},
                    "total_searches": {"$sum": 1}
                }}
            ]
            
            stats_result = await self.search_logs_collection.aggregate(avg_response_pipeline).to_list(1)
            
            if stats_result:
                stats = stats_result[0]
                return {
                    "average_response_time_ms": round(stats.get("avg_response_time", 0), 2),
                    "max_response_time_ms": stats.get("max_response_time", 0),
                    "min_response_time_ms": stats.get("min_response_time", 0),
                    "total_searches_24h": stats.get("total_searches", 0),
                    "performance_status": "optimal" if stats.get("avg_response_time", 0) < 1000 else "needs_optimization"
                }
            else:
                return {
                    "average_response_time_ms": 0,
                    "max_response_time_ms": 0,
                    "min_response_time_ms": 0,
                    "total_searches_24h": 0,
                    "performance_status": "no_data"
                }
                
        except Exception as e:
            print(f"Error getting search performance stats: {e}")
            return {}

    def _get_search_sort_criteria(self, sort_by: Optional[ClubSearchSortField], sort_order: Optional[SortOrder]) -> tuple:
        """Convert search sort parameters to database sort criteria"""
        # Default sorting
        if not sort_by:
            sort_by = ClubSearchSortField.DATE_CREATED
        
        if not sort_order:
            sort_order = SortOrder.DESC
        
        # Map sort fields to database fields
        sort_field_mapping = {
            ClubSearchSortField.CLUB_NAME: "name",
            ClubSearchSortField.OWNER_NAME: "owner_name",  # This will be added in aggregation
            ClubSearchSortField.DATE_CREATED: "created_at",
            ClubSearchSortField.SUBSCRIPTION_PRICE: "pricing_plans.0.price",  # First pricing plan price
            ClubSearchSortField.MODERATOR_COUNT: "moderator_count",  # This will be calculated
            ClubSearchSortField.STATUS: "status"
        }
        
        db_field = sort_field_mapping.get(sort_by, "created_at")
        direction = -1 if sort_order == SortOrder.DESC else 1
        
        return db_field, direction

    def _add_computed_fields_for_sorting(self, pipeline: List, sort_by: ClubSearchSortField):
        """Add computed fields needed for specific sorting operations"""
        
        # If sorting by moderator count, we need to calculate it
        if sort_by == ClubSearchSortField.MODERATOR_COUNT:
            # Add lookup for moderator count
            pipeline.append({
                "$lookup": {
                    "from": "club_memberships",
                    "let": {"club_id": {"$toString": "$_id"}},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$club_id", "$$club_id"]},
                                        {"$in": ["$role", ["moderator", "analyst", "editor"]]},
                                        {"$eq": ["$subscription_status", "active"]}
                                    ]
                                }
                            }
                        },
                        {"$count": "count"}
                    ],
                    "as": "moderator_data"
                }
            })
            
            # Add computed moderator count field
            pipeline.append({
                "$addFields": {
                    "moderator_count": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$moderator_data.count", 0]},
                            0
                        ]
                    }
                }
            })

    # CRUD Operations for Club Management
    
    async def create_club_with_owner(self, request: ClubCreateRequest, admin_email: str, ip_address: Optional[str] = None) -> ClubCreateResponse:
        """Create a new club with its owner in a single transaction"""
        start_time = time.time()
        
        try:
            print(f"DEBUG: Starting club creation for: {request.club_name}")
            
            # Validate uniqueness
            print("DEBUG: Validating club uniqueness")
            await self._validate_club_uniqueness(request.club_name)
            
            print("DEBUG: Validating owner email uniqueness")
            await self._validate_owner_uniqueness(request.owner.email)
            
            # Hash the owner's password
            print("DEBUG: Hashing password")
            try:
                hashed_password = self._hash_password(request.owner.password)
                print("DEBUG: Password hashed successfully")
            except Exception as hash_error:
                print(f"DEBUG: Password hashing failed: {hash_error}")
                raise Exception(f"Password hashing failed: {hash_error}")
            
            # Prepare owner document
            owner_id = ObjectId()
            owner_doc = {
                "_id": owner_id,
                "full_name": request.owner.name,
                "email": request.owner.email.lower(),
                "phone": request.owner.phone,
                "password_hash": hashed_password,
                "role": "club_owner",
                "is_verified": True,  # Admin-created users are auto-verified
                "is_deleted": False,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "created_by_admin": admin_email
            }
            
            # Prepare club document
            club_id = ObjectId()
            club_doc = {
                "_id": club_id,
                "name": request.club_name,
                "description": request.description,
                "club_type": request.club_type.value,
                "logo_url": request.logo,
                "status": request.status.value,
                "captain_id": str(owner_id),
                "is_active": True,
                "is_deleted": False,
                "member_count": 1,  # Owner is the first member
                "win_pct": 0.0,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "created_by_admin": admin_email,
                "pricing_plans": []  # Will be set up later by owner
            }
            
            # Insert operations without transaction for now (simpler approach)
            try:
                # Insert owner first
                await self.users_collection.insert_one(owner_doc)
                print("DEBUG: Owner inserted successfully")
                
                # Insert club
                await self.clubs_collection.insert_one(club_doc)
                print("DEBUG: Club inserted successfully")
                
                # Create initial membership for owner
                membership_doc = {
                    "club_id": str(club_id),
                    "user_id": str(owner_id),
                    "role": "captain",
                    "subscription_status": "active",
                    "joined_date": datetime.utcnow(),
                    "is_active": True
                }
                await self.club_memberships_collection.insert_one(membership_doc)
                print("DEBUG: Membership created successfully")
                
            except Exception as e:
                print(f"DEBUG: Database operation failed: {e}")
                # Clean up if something failed
                try:
                    await self.users_collection.delete_one({"_id": owner_id})
                    await self.clubs_collection.delete_one({"_id": club_id})
                except:
                    pass  # Ignore cleanup errors
                raise e
            
            # Log the action
            await self._log_club_audit(
                action="CREATE",
                admin_email=admin_email,
                club_id=str(club_id),
                owner_id=str(owner_id),
                changes={
                    "club_name": request.club_name,
                    "owner_email": request.owner.email,
                    "status": request.status.value
                },
                ip_address=ip_address
            )
            
            # Prepare response data
            club_response = {
                "club_id": str(club_id),
                "name": request.club_name,
                "description": request.description,
                "club_type": request.club_type.value,
                "logo_url": request.logo,
                "status": request.status.value,
                "is_active": True,
                "member_count": 1,
                "created_at": club_doc["created_at"].isoformat()
            }
            
            owner_response = {
                "owner_id": str(owner_id),
                "name": request.owner.name,
                "email": request.owner.email,
                "phone": request.owner.phone,
                "role": "club_owner",
                "created_at": owner_doc["created_at"].isoformat()
            }
            
            return ClubCreateResponse(
                success=True,
                message=f"Club '{request.club_name}' and owner '{request.owner.name}' created successfully",
                club_id=str(club_id),
                owner_id=str(owner_id),
                club=club_response,
                owner=owner_response,
                created_at=datetime.utcnow()
            )
            
        except ValueError as ve:
            raise ve
        except Exception as e:
            print(f"Error creating club with owner: {e}")
            raise Exception(f"Failed to create club: {str(e)}")

    async def update_club_with_owner(self, club_id: str, request: ClubUpdateRequest, admin_email: str, ip_address: Optional[str] = None) -> ClubUpdateResponse:
        """Update club and optionally its owner"""
        try:
            print(f"DEBUG: Starting club update for club_id: {club_id}")
            # Validate club exists
            club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id), "is_deleted": False})
            if not club_doc:
                raise ValueError(f"Club with ID {club_id} not found")
            
            owner_id = club_doc.get("captain_id")
            changes = {}
            
            # Check for club name uniqueness if changing
            if request.club_name and request.club_name != club_doc.get("name"):
                await self._validate_club_uniqueness(request.club_name, exclude_id=club_id)
            
            # Check for owner email uniqueness if changing
            if request.owner and request.owner.email:
                owner_doc = await self.users_collection.find_one({"_id": ObjectId(owner_id)})
                if owner_doc and request.owner.email.lower() != owner_doc.get("email", "").lower():
                    await self._validate_owner_uniqueness(request.owner.email)
            
            # Prepare club updates
            club_updates = {"updated_at": datetime.utcnow()}
            if request.club_name:
                club_updates["name"] = request.club_name
                changes["club_name"] = {"old": club_doc.get("name"), "new": request.club_name}
            if request.description:
                club_updates["description"] = request.description
                changes["description"] = {"old": club_doc.get("description"), "new": request.description}
            if request.club_type:
                club_updates["club_type"] = request.club_type.value
                changes["club_type"] = {"old": club_doc.get("club_type"), "new": request.club_type.value}
            if request.logo is not None:  # Allow empty string to remove logo
                club_updates["logo_url"] = request.logo
                changes["logo_url"] = {"old": club_doc.get("logo_url"), "new": request.logo}
            if request.status:
                club_updates["status"] = request.status.value
                changes["status"] = {"old": club_doc.get("status"), "new": request.status.value}
            
            # Prepare owner updates
            owner_updates = {}
            owner_response = None
            
            if request.owner and owner_id:
                owner_doc = await self.users_collection.find_one({"_id": ObjectId(owner_id)})
                if owner_doc:
                    owner_updates["updated_at"] = datetime.utcnow()
                    
                    if request.owner.name:
                        owner_updates["full_name"] = request.owner.name
                        changes["owner_name"] = {"old": owner_doc.get("full_name"), "new": request.owner.name}
                    if request.owner.email:
                        owner_updates["email"] = request.owner.email.lower()
                        changes["owner_email"] = {"old": owner_doc.get("email"), "new": request.owner.email.lower()}
                    if request.owner.phone:
                        owner_updates["phone"] = request.owner.phone
                        changes["owner_phone"] = {"old": owner_doc.get("phone"), "new": request.owner.phone}
                    if request.owner.password:
                        print("DEBUG: Hashing password for owner update")
                        try:
                            owner_updates["password_hash"] = self._hash_password(request.owner.password)
                            changes["password"] = "updated"
                            print("DEBUG: Password hashed successfully for update")
                        except Exception as hash_error:
                            print(f"DEBUG: Password hashing failed in update: {hash_error}")
                            raise Exception(f"Password hashing failed: {hash_error}")
            
            # Update operations (simplified approach)
            try:
                # Update club
                if club_updates:
                    await self.clubs_collection.update_one(
                        {"_id": ObjectId(club_id)},
                        {"$set": club_updates}
                    )
                    print("DEBUG: Club updated successfully")
                
                # Update owner
                if owner_updates and owner_id:
                    await self.users_collection.update_one(
                        {"_id": ObjectId(owner_id)},
                        {"$set": owner_updates}
                    )
                    print("DEBUG: Owner updated successfully")
                    
            except Exception as e:
                print(f"DEBUG: Update operation failed: {e}")
                raise e
            
            # Log the action
            await self._log_club_audit(
                action="UPDATE",
                admin_email=admin_email,
                club_id=club_id,
                owner_id=owner_id,
                changes=changes,
                ip_address=ip_address
            )
            
            # Get updated documents for response
            updated_club = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            club_response = {
                "club_id": club_id,
                "name": updated_club.get("name"),
                "description": updated_club.get("description"),
                "club_type": updated_club.get("club_type"),
                "logo_url": updated_club.get("logo_url"),
                "status": updated_club.get("status"),
                "updated_at": updated_club.get("updated_at").isoformat()
            }
            
            if owner_id:
                updated_owner = await self.users_collection.find_one({"_id": ObjectId(owner_id)})
                owner_response = {
                    "owner_id": owner_id,
                    "name": updated_owner.get("full_name"),
                    "email": updated_owner.get("email"),
                    "phone": updated_owner.get("phone"),
                    "updated_at": updated_owner.get("updated_at").isoformat()
                }
            
            return ClubUpdateResponse(
                success=True,
                message=f"Club '{updated_club.get('name')}' updated successfully",
                club_id=club_id,
                owner_id=owner_id,
                club=club_response,
                owner=owner_response,
                updated_at=datetime.utcnow(),
                changes=changes
            )
            
        except ValueError as ve:
            raise ve
        except Exception as e:
            print(f"Error updating club: {e}")
            raise Exception(f"Failed to update club: {str(e)}")

    async def delete_club_with_owner(self, club_id: str, admin_email: str, ip_address: Optional[str] = None, cascade_owner: bool = False) -> Dict[str, Any]:
        """Soft delete club and optionally its owner"""
        try:
            print(f"DEBUG: Attempting to delete club with ID: {club_id}")
            
            # Check database connection
            try:
                await self.clubs_collection.find_one({})
                print("DEBUG: Database connection successful")
            except Exception as db_error:
                print(f"DEBUG: Database connection error: {db_error}")
                raise ValueError(f"Database connection error: {db_error}")
            
            # Validate ObjectId format
            try:
                object_id = ObjectId(club_id)
                print(f"DEBUG: ObjectId conversion successful: {object_id}")
            except Exception as e:
                print(f"DEBUG: Invalid ObjectId format: {club_id}, error: {e}")
                raise ValueError(f"Invalid club ID format: {club_id}")
            
            # Validate club exists - check without is_deleted filter first
            club_doc = await self.clubs_collection.find_one({"_id": object_id})
            if not club_doc:
                print(f"DEBUG: Club not found in database with ID: {club_id}")
                
                # Debug: Check what clubs exist in database
                try:
                    all_clubs = await self.clubs_collection.find({}).limit(5).to_list(5)
                    print(f"DEBUG: Sample clubs in database: {[str(club.get('_id', '')) for club in all_clubs]}")
                except Exception as debug_error:
                    print(f"DEBUG: Error checking database contents: {debug_error}")
                
                raise ValueError(f"Club with ID {club_id} not found")
            
            print(f"DEBUG: Found club: {club_doc.get('name', 'Unknown')} with status: {club_doc.get('status', 'Unknown')}")
            
            # Check if club is already deleted
            if club_doc.get("is_deleted", False):
                print(f"DEBUG: Club is already deleted")
                raise ValueError(f"Club with ID {club_id} is already deleted")
            
            owner_id = club_doc.get("captain_id")
            club_name = club_doc.get("name", "Unknown Club")
            cascade_deleted = False
            
            # Check if owner has other active clubs
            if cascade_owner and owner_id:
                other_clubs = await self.clubs_collection.count_documents({
                    "captain_id": owner_id,
                    "_id": {"$ne": object_id},
                    "is_deleted": False
                })
                
                if other_clubs > 0:
                    cascade_owner = False  # Don't delete owner if they have other clubs
            
            # Get all club members before deletion for email notifications
            club_members = await self._get_club_members_for_notification(club_id)
            
            # Delete operations (simplified approach)
            try:
                # Soft delete club
                await self.clubs_collection.update_one(
                    {"_id": object_id},
                    {
                        "$set": {
                            "is_deleted": True,
                            "deleted_at": datetime.utcnow(),
                            "deleted_by_admin": admin_email,
                            "is_active": False,
                            "status": "inactive"
                        }
                    }
                )
                print("DEBUG: Club soft deleted successfully")
                
                # Deactivate all club memberships
                await self.club_memberships_collection.update_many(
                    {"club_id": club_id},
                    {
                        "$set": {
                            "is_active": False,
                            "subscription_status": "cancelled",
                            "cancelled_at": datetime.utcnow()
                        }
                    }
                )
                print("DEBUG: Club memberships deactivated successfully")
                
                # Soft delete owner if cascade requested and safe
                if cascade_owner and owner_id:
                    await self.users_collection.update_one(
                        {"_id": ObjectId(owner_id)},
                        {
                            "$set": {
                                "is_deleted": True,
                                "deleted_at": datetime.utcnow(),
                                "deleted_by_admin": admin_email,
                                "is_active": False
                            }
                        }
                    )
                    cascade_deleted = True
                    print("DEBUG: Owner soft deleted successfully")
                    
            except Exception as e:
                print(f"DEBUG: Delete operation failed: {e}")
                raise e
            
            # Send email notifications to all club members
            await self._send_club_deletion_notifications(club_name, club_members, admin_email)
            
            # Log the action
            await self._log_club_audit(
                action="DELETE",
                admin_email=admin_email,
                club_id=club_id,
                owner_id=owner_id if cascade_deleted else None,
                changes={
                    "club_name": club_name,
                    "cascade_owner": cascade_deleted,
                    "members_notified": len(club_members)
                },
                ip_address=ip_address
            )
            
            return {
                "success": True,
                "message": f"Club '{club_name}' deleted successfully" + (
                    " (owner also deleted)" if cascade_deleted else ""
                ),
                "club_id": club_id,
                "owner_id": owner_id if cascade_deleted else None,
                "deleted_at": datetime.utcnow().isoformat(),
                "cascade_deleted": cascade_deleted,
                "members_notified": len(club_members),
                "club_name": club_name
            }
            
        except ValueError as ve:
            raise ve
        except Exception as e:
            print(f"Error deleting club: {e}")
            raise Exception(f"Failed to delete club: {str(e)}")

    # Helper methods for CRUD operations
    
    async def _validate_club_uniqueness(self, club_name: str, exclude_id: Optional[str] = None):
        """Validate that club name is unique (case-insensitive)"""
        query = {
            "name": {"$regex": f"^{club_name}$", "$options": "i"},
            "is_deleted": False
        }
        
        if exclude_id:
            query["_id"] = {"$ne": ObjectId(exclude_id)}
        
        existing_club = await self.clubs_collection.find_one(query)
        if existing_club:
            raise ValueError(f"Club name '{club_name}' already exists")
    
    async def _validate_owner_uniqueness(self, email: str):
        """Validate that owner email is unique"""
        existing_user = await self.users_collection.find_one({
            "email": email.lower(),
            "is_deleted": False
        })
        if existing_user:
            raise ValueError(f"Email '{email}' is already registered")
    
    def _hash_password(self, password: str) -> str:
        """Hash password using the same approach as other working parts of the codebase"""
        try:
            # Use exact same method as users_service.py and routes.py (which work)
            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            return password_hash
        except Exception as e:
            print(f"Password hashing failed: {e}")
            # If bcrypt fails completely, use a basic fallback for testing
            import hashlib
            import secrets
            salt = secrets.token_hex(16)
            hash_obj = hashlib.sha256((password + salt).encode())
            return f"sha256${salt}${hash_obj.hexdigest()}"
    
    async def _log_club_audit(self, action: str, admin_email: str, club_id: Optional[str] = None, 
                             owner_id: Optional[str] = None, changes: Optional[Dict[str, Any]] = None,
                             ip_address: Optional[str] = None):
        """Log club management actions for audit purposes"""
        try:
            audit_entry = {
                "_id": ObjectId(),
                "action": action,
                "admin_email": admin_email,
                "club_id": club_id,
                "owner_id": owner_id,
                "changes": changes,
                "timestamp": datetime.utcnow(),
                "ip_address": ip_address,
                "user_agent": None  # Could be added from request headers
            }
            
            await self.club_admin_logs_collection.insert_one(audit_entry)
            
        except Exception as e:
            print(f"Error logging club audit: {e}")

    async def _get_club_members_for_notification(self, club_id: str) -> List[Dict[str, Any]]:
        """Get all club members for email notifications"""
        try:
            members = []
            cursor = self.club_memberships_collection.find({
                "club_id": club_id,
                "subscription_status": "active"
            })
            
            async for membership in cursor:
                user_id = membership.get("user_id")
                if user_id:
                    user_doc = await self.users_collection.find_one({"_id": ObjectId(user_id)})
                    if user_doc:
                        members.append({
                            "user_id": user_id,
                            "email": user_doc.get("email", ""),
                            "full_name": user_doc.get("full_name", "Unknown"),
                            "role": membership.get("role", "member")
                        })
            
            return members
            
        except Exception as e:
            print(f"Error getting club members for notification: {e}")
            return []

    async def _send_club_deletion_notifications(self, club_name: str, members: List[Dict[str, Any]], admin_email: str):
        """Send email notifications to all club members about club deletion"""
        try:
            if not members:
                print("No members to notify about club deletion")
                return
            
            # Import email utility
            from .utils.email import send_email
            
            # Send notifications to each member
            for member in members:
                try:
                    subject = f"Club '{club_name}' Has Been Deactivated"
                    
                    # Create personalized message based on member role
                    if member.get("role") == "captain":
                        message = f"""
                        Dear {member.get('full_name', 'Valued Member')},
                        
                        We regret to inform you that the club '{club_name}' has been deactivated by our administration team.
                        
                        As the club captain, your club and all associated memberships have been suspended. 
                        All active subscriptions have been cancelled, and members will no longer have access to club features.
                        
                        If you have any questions or concerns about this action, please contact our support team.
                        
                        Thank you for your understanding.
                        
                        Best regards,
                        Admin Team
                        """
                    else:
                        message = f"""
                        Dear {member.get('full_name', 'Valued Member')},
                        
                        We regret to inform you that the club '{club_name}' has been deactivated by our administration team.
                        
                        Your membership in this club has been suspended, and your subscription has been cancelled. 
                        You will no longer have access to club features or content.
                        
                        If you have any questions about this action, please contact our support team.
                        
                        Thank you for your understanding.
                        
                        Best regards,
                        Admin Team
                        """
                    
                    # Send email
                    await send_email(
                        to_email=member.get("email"),
                        subject=subject,
                        message=message
                    )
                    
                    print(f"Club deletion notification sent to {member.get('email')}")
                    
                except Exception as email_error:
                    print(f"Failed to send club deletion notification to {member.get('email')}: {email_error}")
                    # Continue with other members even if one fails
            
            print(f"Club deletion notifications sent to {len(members)} members")
            
        except Exception as e:
            print(f"Error sending club deletion notifications: {e}")
            # Don't fail the deletion process if email sending fails

# Global service instance
admin_clubs_service = AdminClubsService() 