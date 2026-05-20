"""
Admin Statistics Service - Handle admin dashboard statistics
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List
from bson import ObjectId
from fastapi import HTTPException, status, Query
import logging
import math

from .db import (
    get_users_collection,
    get_clubs_collection,
    get_club_picks_collection
)

logger = logging.getLogger(__name__)


class AdminStatisticsService:
    """Service for managing admin dashboard statistics"""
    
    def __init__(self):
        self.users_collection = get_users_collection()
        self.clubs_collection = get_clubs_collection()
        self.club_picks_collection = get_club_picks_collection()
    
    async def get_dashboard_statistics(
        self, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        month_filter: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict:
        """
        Get comprehensive dashboard statistics for admin
        
        Args:
            start_date: Optional start date in format "YYYY-MM-DD" (e.g., "2024-01-01")
            end_date: Optional end date in format "YYYY-MM-DD" (e.g., "2024-01-31")
            month_filter: Optional month filter in format "YYYY-MM" (e.g., "2024-01") - DEPRECATED
            page: Page number for pagination (default: 1)
            limit: Items per page (default: 20)
        
        Returns:
            Dict containing all requested statistics with pagination info
        """
        try:
            # Get current time for calculations
            now = datetime.now(timezone.utc)
            last_24_hours = now - timedelta(hours=24)
            
            # Calculate date range - prioritize start_date/end_date over month_filter
            date_start, date_end = self._get_date_range(start_date, end_date, month_filter, now)
            
            # Execute all queries in parallel for better performance
            stats = await self._get_all_statistics(now, last_24_hours, date_start, date_end, page, limit, start_date, end_date, month_filter)
            
            return {
                "total_registered_users": stats["total_users"],
                "newly_registered_last_24h": stats["new_users_24h"],
                "users_registered_selected_period": stats["new_users_selected_period"],
                "total_approved_clubs": stats["approved_clubs"],
                "total_pending_clubs": stats["pending_clubs"],
                "total_clubs": stats["total_clubs"],
                "total_picks": stats["total_picks"],
                "club_requests_last_24h": {
                    "count": stats["club_requests_24h"]["count"],
                    "club_names": stats["club_requests_24h"]["club_names"]
                },
                "user_role_breakdown": stats["user_role_breakdown"],
                "user_status_breakdown": stats["user_status_breakdown"],
                "date_range": {
                    "start_date": date_start.isoformat() if date_start else None,
                    "end_date": date_end.isoformat() if date_end else None,
                    "start_date_formatted": date_start.strftime("%Y-%m-%d") if date_start else None,
                    "end_date_formatted": date_end.strftime("%Y-%m-%d") if date_end else None
                },
                "month_filter": month_filter,  # Keep for backward compatibility
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total_pages": stats["total_pages"]
                },
                "generated_at": now.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting dashboard statistics: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get dashboard statistics: {str(e)}"
            )
    
    def _get_date_range(self, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str], now: datetime) -> tuple:
        """
        Get start and end dates based on the provided parameters
        
        Priority:
        1. If start_date and/or end_date are provided, use them
        2. If month_filter is provided (and no start_date/end_date), use month filter
        3. If none provided, use current month first date to today
        
        Args:
            start_date: Start date in format "YYYY-MM-DD" or None
            end_date: End date in format "YYYY-MM-DD" or None
            month_filter: Month filter in format "YYYY-MM" or None (DEPRECATED)
            now: Current datetime
            
        Returns:
            Tuple of (date_start, date_end) datetime objects
        """
        try:
            # Priority 1: Use start_date and end_date if provided
            if start_date or end_date:
                if start_date:
                    try:
                        date_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    except ValueError:
                        logger.warning(f"Invalid start_date format: {start_date}, using current month first date")
                        date_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                else:
                    # No start_date provided, use current month first date
                    date_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                if end_date:
                    try:
                        date_end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        # Add 1 day to end_date to include the entire end date
                        date_end = date_end.replace(hour=23, minute=59, second=59, microsecond=999999)
                    except ValueError:
                        logger.warning(f"Invalid end_date format: {end_date}, using today's date")
                        date_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                else:
                    # No end_date provided, use today's date
                    date_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                
                return date_start, date_end
            
            # Priority 2: Use month_filter if provided (DEPRECATED)
            elif month_filter:
                logger.warning("month_filter is deprecated, please use start_date and end_date parameters")
                return self._get_month_filter_dates(month_filter, now)
            
            # Priority 3: Default to current month first date to today
            else:
                date_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                date_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                return date_start, date_end
                
        except Exception as e:
            logger.error(f"Error calculating date range: {e}")
            # Fallback to current month
            date_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            date_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            return date_start, date_end
    
    def _get_month_filter_dates(self, month_filter: Optional[str], now: datetime) -> tuple:
        """
        Get start and end dates for month filter
        
        Args:
            month_filter: Month filter in format "YYYY-MM" or None
            now: Current datetime
            
        Returns:
            Tuple of (month_start, month_end) datetime objects
        """
        if month_filter:
            try:
                year, month = map(int, month_filter.split('-'))
                month_start = datetime(year, month, 1, tzinfo=timezone.utc)
                if month == 12:
                    month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
                else:
                    month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
                return month_start, month_end
            except (ValueError, IndexError):
                # If month filter is invalid, use current month
                logger.warning(f"Invalid month filter format: {month_filter}, using current month")
                current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                if now.month == 12:
                    current_month_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                else:
                    current_month_end = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
                return current_month_start, current_month_end
        else:
            # No month filter, use current month
            current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now.month == 12:
                current_month_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                current_month_end = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            return current_month_start, current_month_end
    
    async def _get_all_statistics(self, now: datetime, last_24_hours: datetime, date_start: datetime, date_end: datetime, page: int, limit: int, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str]) -> Dict:
        """
        Get all statistics in parallel for better performance
        """
        import asyncio
        
        # Define all the async operations
        tasks = [
            self._get_total_users(date_start, date_end, start_date, end_date, month_filter),
            self._get_new_users_24h(last_24_hours),
            self._get_new_users_selected_period(date_start, date_end),
            self._get_approved_clubs(date_start, date_end, start_date, end_date, month_filter),
            self._get_pending_clubs(date_start, date_end, start_date, end_date, month_filter),
            self._get_total_clubs(date_start, date_end, start_date, end_date, month_filter),
            self._get_total_picks(date_start, date_end, start_date, end_date, month_filter),
            self._get_club_requests_24h(last_24_hours),
            self._get_total_pages(limit, date_start, date_end, start_date, end_date, month_filter),
            self._get_user_role_breakdown(date_start, date_end, start_date, end_date, month_filter),
            self._get_user_status_breakdown(date_start, date_end, start_date, end_date, month_filter)
        ]
        
        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks)
        
        return {
            "total_users": results[0],
            "new_users_24h": results[1],
            "new_users_selected_period": results[2],
            "approved_clubs": results[3],
            "pending_clubs": results[4],
            "total_clubs": results[5],
            "total_picks": results[6],
            "club_requests_24h": results[7],
            "total_pages": results[8],
            "user_role_breakdown": results[9],
            "user_status_breakdown": results[10]
        }
    
    async def _get_total_users(self, date_start: datetime, date_end: datetime, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str]) -> int:
        """Get total number of registered users (filtered by date range)"""
        try:
            # Always apply date filtering (default or custom)
            query = {"created_at": {"$gte": date_start, "$lte": date_end}}
            
            return await self.users_collection.count_documents(query)
        except Exception as e:
            logger.error(f"Error getting total users: {e}")
            return 0
    
    async def _get_new_users_24h(self, last_24_hours: datetime) -> int:
        """Get number of users registered in last 24 hours"""
        try:
            return await self.users_collection.count_documents({
                "created_at": {"$gte": last_24_hours}
            })
        except Exception as e:
            logger.error(f"Error getting new users 24h: {e}")
            return 0
    
    async def _get_new_users_selected_period(self, date_start: datetime, date_end: datetime) -> int:
        """Get number of users registered in selected period"""
        try:
            return await self.users_collection.count_documents({
                "created_at": {"$gte": date_start, "$lte": date_end}
            })
        except Exception as e:
            logger.error(f"Error getting new users selected period: {e}")
            return 0
    
    async def _get_approved_clubs(self, date_start: datetime, date_end: datetime, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str]) -> int:
        """Get total number of approved clubs (filtered by date range)"""
        try:
            # Always apply date filtering (default or custom)
            query = {
                "status": "approved",
                "created_at": {"$gte": date_start, "$lte": date_end}
            }
            
            return await self.clubs_collection.count_documents(query)
        except Exception as e:
            logger.error(f"Error getting approved clubs: {e}")
            return 0
    
    async def _get_pending_clubs(self, date_start: datetime, date_end: datetime, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str]) -> int:
        """Get total number of pending clubs (filtered by date range)"""
        try:
            # Always apply date filtering (default or custom)
            query = {
                "status": "pending",
                "created_at": {"$gte": date_start, "$lte": date_end}
            }
            
            return await self.clubs_collection.count_documents(query)
        except Exception as e:
            logger.error(f"Error getting pending clubs: {e}")
            return 0
    
    async def _get_total_clubs(self, date_start: datetime, date_end: datetime, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str]) -> int:
        """Get total number of clubs (pending + approved + rejected) (filtered by date range)"""
        try:
            # Always apply date filtering (default or custom)
            query = {
                "status": {"$in": ["pending", "approved", "rejected"]},
                "created_at": {"$gte": date_start, "$lte": date_end}
            }
            
            return await self.clubs_collection.count_documents(query)
        except Exception as e:
            logger.error(f"Error getting total clubs: {e}")
            return 0
    
    async def _get_total_picks(self, date_start: datetime, date_end: datetime, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str]) -> int:
        """Get total number of picks (filtered by date range)"""
        try:
            # Always apply date filtering (default or custom)
            query = {
                "is_active": True,
                "created_at": {"$gte": date_start, "$lte": date_end}
            }
            
            return await self.club_picks_collection.count_documents(query)
        except Exception as e:
            logger.error(f"Error getting total picks: {e}")
            return 0
    
    async def _get_club_requests_24h(self, last_24_hours: datetime) -> Dict:
        """Get club requests received in last 24 hours with names"""
        try:
            # Get club requests from last 24 hours
            clubs = await self.clubs_collection.find({
                "created_at": {"$gte": last_24_hours}
            }).to_list(length=None)
            
            # Extract club names and count
            club_names = [club.get("name", "Unknown") for club in clubs]
            count = len(clubs)
            
            return {
                "count": count,
                "club_names": club_names
            }
        except Exception as e:
            logger.error(f"Error getting club requests 24h: {e}")
            return {"count": 0, "club_names": []}
    
    async def _get_total_pages(self, limit: int, date_start: datetime, date_end: datetime, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str]) -> int:
        """Get total pages for pagination (filtered by date range)"""
        try:
            # Always apply date filtering (default or custom)
            query = {"created_at": {"$gte": date_start, "$lte": date_end}}
            
            total_docs = await self.users_collection.count_documents(query)
            return math.ceil(total_docs / limit) if limit > 0 else 1
        except Exception as e:
            logger.error(f"Error getting total pages: {e}")
            return 1
    
    async def _get_user_role_breakdown(self, date_start: datetime, date_end: datetime, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str]) -> Dict:
        """Get breakdown of users by role (Captain, Moderator, Member)"""
        try:
            # Always apply date filtering (default or custom)
            base_query = {"created_at": {"$gte": date_start, "$lte": date_end}}
            
            # Aggregate users by role
            pipeline = [
                {"$match": base_query},
                {
                    "$group": {
                        "_id": "$role",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            role_stats = await self.users_collection.aggregate(pipeline).to_list(length=None)
            
            # Initialize with zeros for all roles
            role_breakdown = {
                "total_captains": 0,
                "total_moderators": 0,
                "total_members": 0
            }
            
            # Fill in the actual counts
            for stat in role_stats:
                role = stat["_id"]
                count = stat["count"]
                
                if role == "Captain":
                    role_breakdown["total_captains"] = count
                elif role == "Moderator" or role == "moderator":
                    role_breakdown["total_moderators"] = count
                elif role == "Member" or role == "member":
                    role_breakdown["total_members"] = count
            
            return role_breakdown
            
        except Exception as e:
            logger.error(f"Error getting user role breakdown: {e}")
            return {
                "total_captains": 0,
                "total_moderators": 0,
                "total_members": 0
            }
    
    async def _get_user_status_breakdown(self, date_start: datetime, date_end: datetime, start_date: Optional[str], end_date: Optional[str], month_filter: Optional[str]) -> Dict:
        """Get breakdown of users by status and role combinations"""
        try:
            # Always apply date filtering (default or custom)
            base_query = {"created_at": {"$gte": date_start, "$lte": date_end}}
            
            # Aggregate users by role and status
            pipeline = [
                {"$match": base_query},
                {
                    "$group": {
                        "_id": {
                            "role": "$role",
                            "status": "$status"
                        },
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            role_status_stats = await self.users_collection.aggregate(pipeline).to_list(length=None)
            
            # Initialize breakdown structure
            status_breakdown = {
                "total_active_users": 0,
                "total_inactive_users": 0,
                "captains": {
                    "active": 0,
                    "inactive": 0,
                    "total": 0
                },
                "moderators": {
                    "active": 0,
                    "inactive": 0,
                    "total": 0
                },
                "members": {
                    "active": 0,
                    "inactive": 0,
                    "total": 0
                }
            }
            
            # Fill in the actual counts
            for stat in role_status_stats:
                role = stat["_id"]["role"]
                status = stat["_id"]["status"]
                count = stat["count"]
                
                # Count total active/inactive users
                if status == "active":
                    status_breakdown["total_active_users"] += count
                elif status == "inactive" or status == "pending" or status == "deleted":
                    status_breakdown["total_inactive_users"] += count
                
                # Count by role and status
                if role == "Captain":
                    if status == "active":
                        status_breakdown["captains"]["active"] = count
                    elif status == "inactive" or status == "pending" or status == "deleted":
                        status_breakdown["captains"]["inactive"] += count
                    status_breakdown["captains"]["total"] += count
                    
                elif role == "Moderator" or role == "moderator":
                    if status == "active":
                        status_breakdown["moderators"]["active"] = count
                    elif status == "inactive" or status == "pending" or status == "deleted":
                        status_breakdown["moderators"]["inactive"] += count
                    status_breakdown["moderators"]["total"] += count
                    
                elif role == "Member" or role == "member":
                    if status == "active":
                        status_breakdown["members"]["active"] = count
                    elif status == "inactive" or status == "pending" or status == "deleted":
                        status_breakdown["members"]["inactive"] += count
                    status_breakdown["members"]["total"] += count
            
            return status_breakdown
            
        except Exception as e:
            logger.error(f"Error getting user status breakdown: {e}")
            return {
                "total_active_users": 0,
                "total_inactive_users": 0,
                "captains": {
                    "active": 0,
                    "inactive": 0,
                    "total": 0
                },
                "moderators": {
                    "active": 0,
                    "inactive": 0,
                    "total": 0
                },
                "members": {
                    "active": 0,
                    "inactive": 0,
                    "total": 0
                }
            }
    
    async def get_detailed_user_statistics(self, month_filter: Optional[str] = None) -> Dict:
        """
        Get detailed user statistics for admin
        
        Args:
            month_filter: Optional month filter in format "YYYY-MM" (e.g., "2024-01")
        
        Returns:
            Dict containing detailed user statistics
        """
        try:
            now = datetime.now(timezone.utc)
            last_7_days = now - timedelta(days=7)
            last_30_days = now - timedelta(days=30)
            
            # Calculate month filter dates if provided
            month_start, month_end = self._get_month_filter_dates(month_filter, now)
            
            # Get user statistics by role
            pipeline = [
                {
                    "$group": {
                        "_id": "$role",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            role_stats = await self.users_collection.aggregate(pipeline).to_list(length=None)
            
            # Get registration trends
            last_7_days_count = await self.users_collection.count_documents({
                "created_at": {"$gte": last_7_days}
            })
            
            last_30_days_count = await self.users_collection.count_documents({
                "created_at": {"$gte": last_30_days}
            })
            
            # Get selected month count
            selected_month_count = await self.users_collection.count_documents({
                "created_at": {"$gte": month_start, "$lt": month_end}
            })
            
            return {
                "role_distribution": {stat["_id"]: stat["count"] for stat in role_stats},
                "registrations_last_7_days": last_7_days_count,
                "registrations_last_30_days": last_30_days_count,
                "registrations_selected_month": selected_month_count,
                "month_filter": month_filter,
                "generated_at": now.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting detailed user statistics: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get detailed user statistics: {str(e)}"
            )
    
    async def get_detailed_club_statistics(self, month_filter: Optional[str] = None) -> Dict:
        """
        Get detailed club statistics for admin
        
        Args:
            month_filter: Optional month filter in format "YYYY-MM" (e.g., "2024-01")
        
        Returns:
            Dict containing detailed club statistics
        """
        try:
            now = datetime.now(timezone.utc)
            last_7_days = now - timedelta(days=7)
            last_30_days = now - timedelta(days=30)
            
            # Calculate month filter dates if provided
            month_start, month_end = self._get_month_filter_dates(month_filter, now)
            
            # Get club statistics by status
            pipeline = [
                {
                    "$group": {
                        "_id": "$status",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            status_stats = await self.clubs_collection.aggregate(pipeline).to_list(length=None)
            
            # Get club creation trends
            last_7_days_count = await self.clubs_collection.count_documents({
                "created_at": {"$gte": last_7_days}
            })
            
            last_30_days_count = await self.clubs_collection.count_documents({
                "created_at": {"$gte": last_30_days}
            })
            
            # Get selected month count
            selected_month_count = await self.clubs_collection.count_documents({
                "created_at": {"$gte": month_start, "$lt": month_end}
            })
            
            return {
                "status_distribution": {stat["_id"]: stat["count"] for stat in status_stats},
                "clubs_created_last_7_days": last_7_days_count,
                "clubs_created_last_30_days": last_30_days_count,
                "clubs_created_selected_month": selected_month_count,
                "month_filter": month_filter,
                "generated_at": now.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting detailed club statistics: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get detailed club statistics: {str(e)}"
            )


# Singleton instance
_service_instance = None

def get_admin_statistics_service() -> AdminStatisticsService:
    """Get singleton instance of AdminStatisticsService"""
    global _service_instance
    if _service_instance is None:
        _service_instance = AdminStatisticsService()
    return _service_instance
