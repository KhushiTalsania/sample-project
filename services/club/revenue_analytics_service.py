"""
Revenue Analytics Service

This service handles revenue tracking, analytics, and reporting for the platform
including platform revenue, captain earnings, and financial insights.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from .db import get_club_collection, get_user_collection
from .datetime_utils import safe_datetime_serialize

# Configure logging
logger = logging.getLogger(__name__)

class RevenueAnalyticsService:
    """Service for revenue analytics and tracking"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
        self.revenue_collection = self.club_collection.database['revenue_tracking']
        self.payout_collection = self.club_collection.database['payout_tracking']
    
    # ==================== PLATFORM REVENUE ANALYTICS ====================
    
    async def get_platform_revenue_summary(self, start_date: Optional[datetime] = None, 
                                         end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get platform revenue summary
        
        Args:
            start_date: Start date for analysis (default: 30 days ago)
            end_date: End date for analysis (default: now)
            
        Returns:
            Dict with platform revenue summary
        """
        try:
            # Default to last 30 days if no dates provided
            if not end_date:
                end_date = datetime.utcnow()
            if not start_date:
                start_date = end_date - timedelta(days=30)
            
            logger.info(f"📊 Getting platform revenue summary from {start_date} to {end_date}")
            
            # Get platform revenue data
            pipeline = [
                {
                    "$match": {
                        "created_at": {"$gte": start_date, "$lte": end_date},
                        "status": "completed"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_revenue": {"$sum": "$total_amount"},
                        "platform_fees": {"$sum": "$platform_fee"},
                        "captain_payments": {"$sum": "$captain_amount"},
                        "total_transactions": {"$sum": 1},
                        "unique_captains": {"$addToSet": "$captain_id"},
                        "unique_clubs": {"$addToSet": "$club_id"}
                    }
                },
                {
                    "$project": {
                        "total_revenue": 1,
                        "platform_fees": 1,
                        "captain_payments": 1,
                        "total_transactions": 1,
                        "unique_captain_count": {"$size": "$unique_captains"},
                        "unique_club_count": {"$size": "$unique_clubs"},
                        "platform_fee_percentage": {
                            "$multiply": [
                                {"$divide": ["$platform_fees", "$total_revenue"]},
                                100
                            ]
                        }
                    }
                }
            ]
            
            result = await self.revenue_collection.aggregate(pipeline).to_list(None)
            
            if result:
                summary = result[0]
                summary["period"] = {
                    "start_date": safe_datetime_serialize(start_date),
                    "end_date": safe_datetime_serialize(end_date),
                    "days": (end_date - start_date).days
                }
                summary["average_transaction_value"] = summary["total_revenue"] / summary["total_transactions"] if summary["total_transactions"] > 0 else 0
                summary["average_platform_fee_per_transaction"] = summary["platform_fees"] / summary["total_transactions"] if summary["total_transactions"] > 0 else 0
            else:
                summary = {
                    "total_revenue": 0,
                    "platform_fees": 0,
                    "captain_payments": 0,
                    "total_transactions": 0,
                    "unique_captain_count": 0,
                    "unique_club_count": 0,
                    "platform_fee_percentage": 0,
                    "average_transaction_value": 0,
                    "average_platform_fee_per_transaction": 0,
                    "period": {
                    "start_date": safe_datetime_serialize(start_date),
                    "end_date": safe_datetime_serialize(end_date),
                        "days": (end_date - start_date).days
                    }
                }
            
            logger.info(f"✅ Platform revenue summary retrieved: ${summary['total_revenue']}")
            return {"success": True, "data": summary}
            
        except Exception as e:
            logger.error(f"❌ Error getting platform revenue summary: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_daily_revenue_trends(self, days: int = 30) -> Dict[str, Any]:
        """
        Get daily revenue trends
        
        Args:
            days: Number of days to analyze (default: 30)
            
        Returns:
            Dict with daily revenue trends
        """
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            logger.info(f"📈 Getting daily revenue trends for {days} days")
            
            pipeline = [
                {
                    "$match": {
                        "created_at": {"$gte": start_date, "$lte": end_date},
                        "status": "completed"
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "year": {"$year": "$created_at"},
                            "month": {"$month": "$created_at"},
                            "day": {"$dayOfMonth": "$created_at"}
                        },
                        "daily_revenue": {"$sum": "$total_amount"},
                        "platform_fees": {"$sum": "$platform_fee"},
                        "captain_payments": {"$sum": "$captain_amount"},
                        "transaction_count": {"$sum": 1}
                    }
                },
                {
                    "$sort": {"_id.year": 1, "_id.month": 1, "_id.day": 1}
                }
            ]
            
            daily_trends = await self.revenue_collection.aggregate(pipeline).to_list(None)
            
            # Format the data
            formatted_trends = []
            for trend in daily_trends:
                date = datetime(trend["_id"]["year"], trend["_id"]["month"], trend["_id"]["day"])
                formatted_trends.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "revenue": trend["daily_revenue"],
                    "platform_fees": trend["platform_fees"],
                    "captain_payments": trend["captain_payments"],
                    "transaction_count": trend["transaction_count"]
                })
            
            logger.info(f"✅ Daily revenue trends retrieved: {len(formatted_trends)} days")
            return {"success": True, "data": formatted_trends}
            
        except Exception as e:
            logger.error(f"❌ Error getting daily revenue trends: {e}")
            return {"success": False, "error": str(e)}
    
    # ==================== CAPTAIN EARNINGS ANALYTICS ====================
    
    async def get_captain_earnings_summary(self, captain_id: str, 
                                         start_date: Optional[datetime] = None,
                                         end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get captain's earnings summary
        
        Args:
            captain_id: Captain's user ID
            start_date: Start date for analysis
            end_date: End date for analysis
            
        Returns:
            Dict with captain earnings summary
        """
        try:
            # Default to last 30 days if no dates provided
            if not end_date:
                end_date = datetime.utcnow()
            if not start_date:
                start_date = end_date - timedelta(days=30)
            
            logger.info(f"💰 Getting earnings summary for captain: {captain_id}")
            
            # Get captain's earnings
            pipeline = [
                {
                    "$match": {
                        "captain_id": ObjectId(captain_id),
                        "created_at": {"$gte": start_date, "$lte": end_date},
                        "status": "completed"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_earnings": {"$sum": "$captain_amount"},
                        "platform_fees_paid": {"$sum": "$platform_fee"},
                        "total_revenue": {"$sum": "$total_amount"},
                        "transaction_count": {"$sum": 1},
                        "unique_clubs": {"$addToSet": "$club_id"}
                    }
                },
                {
                    "$project": {
                        "total_earnings": 1,
                        "platform_fees_paid": 1,
                        "total_revenue": 1,
                        "transaction_count": 1,
                        "unique_club_count": {"$size": "$unique_clubs"},
                        "average_earning_per_transaction": {"$divide": ["$total_earnings", "$transaction_count"]},
                        "platform_fee_percentage": {
                            "$multiply": [
                                {"$divide": ["$platform_fees_paid", "$total_revenue"]},
                                100
                            ]
                        }
                    }
                }
            ]
            
            result = await self.revenue_collection.aggregate(pipeline).to_list(None)
            
            if result:
                summary = result[0]
                summary["period"] = {
                    "start_date": safe_datetime_serialize(start_date),
                    "end_date": safe_datetime_serialize(end_date),
                    "days": (end_date - start_date).days
                }
            else:
                summary = {
                    "total_earnings": 0,
                    "platform_fees_paid": 0,
                    "total_revenue": 0,
                    "transaction_count": 0,
                    "unique_club_count": 0,
                    "average_earning_per_transaction": 0,
                    "platform_fee_percentage": 0,
                    "period": {
                    "start_date": safe_datetime_serialize(start_date),
                    "end_date": safe_datetime_serialize(end_date),
                        "days": (end_date - start_date).days
                    }
                }
            
            logger.info(f"✅ Captain earnings summary retrieved: ${summary['total_earnings']}")
            return {"success": True, "data": summary}
            
        except Exception as e:
            logger.error(f"❌ Error getting captain earnings summary: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_top_earning_captains(self, limit: int = 10, 
                                     start_date: Optional[datetime] = None,
                                     end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get top earning captains
        
        Args:
            limit: Number of captains to return (default: 10)
            start_date: Start date for analysis
            end_date: End date for analysis
            
        Returns:
            Dict with top earning captains
        """
        try:
            # Default to last 30 days if no dates provided
            if not end_date:
                end_date = datetime.utcnow()
            if not start_date:
                start_date = end_date - timedelta(days=30)
            
            logger.info(f"🏆 Getting top {limit} earning captains")
            
            pipeline = [
                {
                    "$match": {
                        "created_at": {"$gte": start_date, "$lte": end_date},
                        "status": "completed"
                    }
                },
                {
                    "$group": {
                        "_id": "$captain_id",
                        "total_earnings": {"$sum": "$captain_amount"},
                        "platform_fees_paid": {"$sum": "$platform_fee"},
                        "total_revenue": {"$sum": "$total_amount"},
                        "transaction_count": {"$sum": 1},
                        "unique_clubs": {"$addToSet": "$club_id"}
                    }
                },
                {
                    "$project": {
                        "captain_id": 1,
                        "total_earnings": 1,
                        "platform_fees_paid": 1,
                        "total_revenue": 1,
                        "transaction_count": 1,
                        "unique_club_count": {"$size": "$unique_clubs"},
                        "average_earning_per_transaction": {"$divide": ["$total_earnings", "$transaction_count"]}
                    }
                },
                {
                    "$sort": {"total_earnings": -1}
                },
                {
                    "$limit": limit
                }
            ]
            
            top_captains = await self.revenue_collection.aggregate(pipeline).to_list(None)
            
            # Get captain details
            captain_details = []
            for captain in top_captains:
                captain_info = await self.user_collection.find_one(
                    {"_id": captain["_id"]},
                    {"full_name": 1, "email": 1}
                )
                
                captain_details.append({
                    "captain_id": str(captain["_id"]),
                    "captain_name": captain_info.get("full_name", "Unknown") if captain_info else "Unknown",
                    "captain_email": captain_info.get("email", "Unknown") if captain_info else "Unknown",
                    "total_earnings": captain["total_earnings"],
                    "platform_fees_paid": captain["platform_fees_paid"],
                    "total_revenue": captain["total_revenue"],
                    "transaction_count": captain["transaction_count"],
                    "unique_club_count": captain["unique_club_count"],
                    "average_earning_per_transaction": captain["average_earning_per_transaction"]
                })
            
            logger.info(f"✅ Top {len(captain_details)} earning captains retrieved")
            return {"success": True, "data": captain_details}
            
        except Exception as e:
            logger.error(f"❌ Error getting top earning captains: {e}")
            return {"success": False, "error": str(e)}
    
    # ==================== CLUB REVENUE ANALYTICS ====================
    
    async def get_club_revenue_summary(self, club_id: str,
                                     start_date: Optional[datetime] = None,
                                     end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get club's revenue summary
        
        Args:
            club_id: Club ID
            start_date: Start date for analysis
            end_date: End date for analysis
            
        Returns:
            Dict with club revenue summary
        """
        try:
            # Default to last 30 days if no dates provided
            if not end_date:
                end_date = datetime.utcnow()
            if not start_date:
                start_date = end_date - timedelta(days=30)
            
            logger.info(f"🏢 Getting revenue summary for club: {club_id}")
            
            pipeline = [
                {
                    "$match": {
                        "club_id": ObjectId(club_id),
                        "created_at": {"$gte": start_date, "$lte": end_date},
                        "status": "completed"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_revenue": {"$sum": "$total_amount"},
                        "captain_earnings": {"$sum": "$captain_amount"},
                        "platform_fees": {"$sum": "$platform_fee"},
                        "transaction_count": {"$sum": 1},
                        "unique_customers": {"$addToSet": "$customer_id"}
                    }
                },
                {
                    "$project": {
                        "total_revenue": 1,
                        "captain_earnings": 1,
                        "platform_fees": 1,
                        "transaction_count": 1,
                        "unique_customer_count": {"$size": "$unique_customers"},
                        "average_transaction_value": {"$divide": ["$total_revenue", "$transaction_count"]}
                    }
                }
            ]
            
            result = await self.revenue_collection.aggregate(pipeline).to_list(None)
            
            if result:
                summary = result[0]
                summary["period"] = {
                    "start_date": safe_datetime_serialize(start_date),
                    "end_date": safe_datetime_serialize(end_date),
                    "days": (end_date - start_date).days
                }
            else:
                summary = {
                    "total_revenue": 0,
                    "captain_earnings": 0,
                    "platform_fees": 0,
                    "transaction_count": 0,
                    "unique_customer_count": 0,
                    "average_transaction_value": 0,
                    "period": {
                    "start_date": safe_datetime_serialize(start_date),
                    "end_date": safe_datetime_serialize(end_date),
                        "days": (end_date - start_date).days
                    }
                }
            
            logger.info(f"✅ Club revenue summary retrieved: ${summary['total_revenue']}")
            return {"success": True, "data": summary}
            
        except Exception as e:
            logger.error(f"❌ Error getting club revenue summary: {e}")
            return {"success": False, "error": str(e)}
    
    # ==================== FINANCIAL INSIGHTS ====================
    
    async def get_financial_insights(self) -> Dict[str, Any]:
        """
        Get comprehensive financial insights
        
        Returns:
            Dict with financial insights
        """
        try:
            logger.info("💡 Getting comprehensive financial insights")
            
            # Get overall platform metrics
            platform_summary = await self.get_platform_revenue_summary()
            
            # Get daily trends
            daily_trends = await self.get_daily_revenue_trends(30)
            
            # Get top captains
            top_captains = await self.get_top_earning_captains(5)
            
            # Calculate growth metrics
            current_month = await self.get_platform_revenue_summary(
                start_date=datetime.utcnow().replace(day=1),
                end_date=datetime.utcnow()
            )
            
            last_month = await self.get_platform_revenue_summary(
                start_date=(datetime.utcnow().replace(day=1) - timedelta(days=1)).replace(day=1),
                end_date=datetime.utcnow().replace(day=1) - timedelta(days=1)
            )
            
            # Calculate growth percentage
            current_revenue = current_month["data"]["total_revenue"] if current_month["success"] else 0
            last_revenue = last_month["data"]["total_revenue"] if last_month["success"] else 0
            
            growth_percentage = 0
            if last_revenue > 0:
                growth_percentage = ((current_revenue - last_revenue) / last_revenue) * 100
            
            insights = {
                "platform_metrics": platform_summary["data"] if platform_summary["success"] else {},
                "daily_trends": daily_trends["data"] if daily_trends["success"] else [],
                "top_captains": top_captains["data"] if top_captains["success"] else [],
                "growth_metrics": {
                    "current_month_revenue": current_revenue,
                    "last_month_revenue": last_revenue,
                    "growth_percentage": growth_percentage,
                    "growth_direction": "up" if growth_percentage > 0 else "down" if growth_percentage < 0 else "stable"
                },
                "generated_at": safe_datetime_serialize(datetime.utcnow())
            }
            
            logger.info("✅ Financial insights generated successfully")
            return {"success": True, "data": insights}
            
        except Exception as e:
            logger.error(f"❌ Error generating financial insights: {e}")
            return {"success": False, "error": str(e)}

# Global instance
revenue_analytics_service = RevenueAnalyticsService()

def get_revenue_analytics_service():
    """Get revenue analytics service instance"""
    return revenue_analytics_service
