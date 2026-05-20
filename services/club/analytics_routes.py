"""
Analytics API Routes

This module contains API endpoints for revenue analytics, financial insights,
and reporting functionality.
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

from .revenue_analytics_service import get_revenue_analytics_service
from core.utils.response_utils import create_response
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/analytics", tags=["Analytics"])

# ==================== REQUEST/RESPONSE MODELS ====================

class DateRangeRequest(BaseModel):
    """Request model for date range queries"""
    start_date: Optional[datetime] = Field(None, description="Start date for analysis")
    end_date: Optional[datetime] = Field(None, description="End date for analysis")

# ==================== PLATFORM ANALYTICS ROUTES ====================

@router.get("/platform/revenue-summary")
async def get_platform_revenue_summary(
    start_date: Optional[datetime] = Query(None, description="Start date for analysis"),
    end_date: Optional[datetime] = Query(None, description="End date for analysis")
):
    """
    Get platform revenue summary
    
    This endpoint provides a comprehensive overview of platform revenue including
    total revenue, platform fees, captain payments, and key metrics.
    
    **Features:**
    - Total revenue and platform fees
    - Transaction counts and averages
    - Unique captains and clubs
    - Platform fee percentage
    - Customizable date range
    
    **Query Parameters:**
    - `start_date`: Start date for analysis (optional, defaults to 30 days ago)
    - `end_date`: End date for analysis (optional, defaults to now)
    
    **Response includes:**
    - Total revenue and platform fees
    - Transaction metrics
    - Captain and club counts
    - Platform fee percentage
    - Analysis period details
    """
    try:
        logger.info("📊 Getting platform revenue summary")
        
        # Get analytics service
        analytics_service = get_revenue_analytics_service()
        
        # Get platform revenue summary
        result = await analytics_service.get_platform_revenue_summary(start_date, end_date)
        
        if result["success"]:
            logger.info("✅ Platform revenue summary retrieved successfully")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Platform revenue summary retrieved successfully",
                data=result["data"]
            )
        else:
            logger.warning(f"❌ Failed to get platform revenue summary: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get platform revenue summary"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting platform revenue summary: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.get("/platform/daily-trends")
async def get_daily_revenue_trends(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze")
):
    """
    Get daily revenue trends
    
    This endpoint provides daily revenue trends over a specified period
    showing revenue, platform fees, and transaction counts by day.
    
    **Features:**
    - Daily revenue breakdown
    - Platform fees by day
    - Transaction counts
    - Configurable time period
    
    **Query Parameters:**
    - `days`: Number of days to analyze (1-365, default: 30)
    
    **Response includes:**
    - Daily revenue data
    - Platform fees per day
    - Transaction counts
    - Date range information
    """
    try:
        logger.info(f"📈 Getting daily revenue trends for {days} days")
        
        # Get analytics service
        analytics_service = get_revenue_analytics_service()
        
        # Get daily trends
        result = await analytics_service.get_daily_revenue_trends(days)
        
        if result["success"]:
            logger.info(f"✅ Daily revenue trends retrieved for {days} days")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message=f"Daily revenue trends retrieved for {days} days",
                data=result["data"]
            )
        else:
            logger.warning(f"❌ Failed to get daily trends: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get daily trends"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting daily trends: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

# ==================== CAPTAIN ANALYTICS ROUTES ====================

@router.get("/captain/{captain_id}/earnings-summary")
async def get_captain_earnings_summary(
    captain_id: str,
    start_date: Optional[datetime] = Query(None, description="Start date for analysis"),
    end_date: Optional[datetime] = Query(None, description="End date for analysis")
):
    """
    Get captain's earnings summary
    
    This endpoint provides a detailed summary of a captain's earnings including
    total earnings, platform fees paid, and transaction metrics.
    
    **Features:**
    - Total earnings and platform fees
    - Transaction counts and averages
    - Club participation metrics
    - Customizable date range
    
    **Path Parameters:**
    - `captain_id`: Captain's user ID
    
    **Query Parameters:**
    - `start_date`: Start date for analysis (optional)
    - `end_date`: End date for analysis (optional)
    
    **Response includes:**
    - Total earnings and fees
    - Transaction metrics
    - Club participation
    - Analysis period details
    """
    try:
        logger.info(f"💰 Getting earnings summary for captain: {captain_id}")
        
        # Get analytics service
        analytics_service = get_revenue_analytics_service()
        
        # Get captain earnings summary
        result = await analytics_service.get_captain_earnings_summary(captain_id, start_date, end_date)
        
        if result["success"]:
            logger.info(f"✅ Captain earnings summary retrieved for: {captain_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Captain earnings summary retrieved successfully",
                data=result["data"]
            )
        else:
            logger.warning(f"❌ Failed to get captain earnings: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get captain earnings summary"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting captain earnings: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

@router.get("/captain/top-earners")
async def get_top_earning_captains(
    limit: int = Query(10, ge=1, le=100, description="Number of captains to return"),
    start_date: Optional[datetime] = Query(None, description="Start date for analysis"),
    end_date: Optional[datetime] = Query(None, description="End date for analysis")
):
    """
    Get top earning captains
    
    This endpoint provides a ranked list of the top earning captains
    based on their total earnings over a specified period.
    
    **Features:**
    - Ranked by total earnings
    - Captain details and metrics
    - Transaction and club counts
    - Configurable limit and date range
    
    **Query Parameters:**
    - `limit`: Number of captains to return (1-100, default: 10)
    - `start_date`: Start date for analysis (optional)
    - `end_date`: End date for analysis (optional)
    
    **Response includes:**
    - Ranked list of captains
    - Earnings and transaction metrics
    - Captain details
    - Club participation counts
    """
    try:
        logger.info(f"🏆 Getting top {limit} earning captains")
        
        # Get analytics service
        analytics_service = get_revenue_analytics_service()
        
        # Get top earning captains
        result = await analytics_service.get_top_earning_captains(limit, start_date, end_date)
        
        if result["success"]:
            logger.info(f"✅ Top {limit} earning captains retrieved")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message=f"Top {limit} earning captains retrieved successfully",
                data=result["data"]
            )
        else:
            logger.warning(f"❌ Failed to get top captains: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get top earning captains"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting top captains: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

# ==================== CLUB ANALYTICS ROUTES ====================

@router.get("/club/{club_id}/revenue-summary")
async def get_club_revenue_summary(
    club_id: str,
    start_date: Optional[datetime] = Query(None, description="Start date for analysis"),
    end_date: Optional[datetime] = Query(None, description="End date for analysis")
):
    """
    Get club's revenue summary
    
    This endpoint provides a detailed summary of a club's revenue including
    total revenue, captain earnings, and customer metrics.
    
    **Features:**
    - Total revenue and captain earnings
    - Transaction counts and averages
    - Customer participation metrics
    - Customizable date range
    
    **Path Parameters:**
    - `club_id`: Club ID
    
    **Query Parameters:**
    - `start_date`: Start date for analysis (optional)
    - `end_date`: End date for analysis (optional)
    
    **Response includes:**
    - Total revenue and earnings
    - Transaction metrics
    - Customer counts
    - Analysis period details
    """
    try:
        logger.info(f"🏢 Getting revenue summary for club: {club_id}")
        
        # Get analytics service
        analytics_service = get_revenue_analytics_service()
        
        # Get club revenue summary
        result = await analytics_service.get_club_revenue_summary(club_id, start_date, end_date)
        
        if result["success"]:
            logger.info(f"✅ Club revenue summary retrieved for: {club_id}")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Club revenue summary retrieved successfully",
                data=result["data"]
            )
        else:
            logger.warning(f"❌ Failed to get club revenue: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get club revenue summary"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting club revenue: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

# ==================== FINANCIAL INSIGHTS ROUTES ====================

@router.get("/financial-insights")
async def get_financial_insights():
    """
    Get comprehensive financial insights
    
    This endpoint provides a comprehensive overview of the platform's financial
    health including revenue trends, growth metrics, and top performers.
    
    **Features:**
    - Platform revenue metrics
    - Daily revenue trends
    - Top performing captains
    - Growth analysis
    - Comprehensive insights
    
    **Response includes:**
    - Platform metrics and trends
    - Growth percentages and direction
    - Top performing captains
    - Daily revenue breakdown
    - Generated timestamp
    """
    try:
        logger.info("💡 Getting comprehensive financial insights")
        
        # Get analytics service
        analytics_service = get_revenue_analytics_service()
        
        # Get financial insights
        result = await analytics_service.get_financial_insights()
        
        if result["success"]:
            logger.info("✅ Financial insights generated successfully")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Financial insights generated successfully",
                data=result["data"]
            )
        else:
            logger.warning(f"❌ Failed to get financial insights: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get financial insights"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting financial insights: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )

# ==================== CUSTOM ANALYTICS ROUTES ====================

@router.post("/custom/date-range")
async def get_custom_analytics(request: DateRangeRequest):
    """
    Get custom analytics for specific date range
    
    This endpoint allows for custom analytics queries with specific date ranges
    and can be extended for more complex reporting needs.
    
    **Features:**
    - Custom date range analysis
    - Flexible reporting
    - Extensible for complex queries
    
    **Request Body:**
    - `start_date`: Start date for analysis (optional)
    - `end_date`: End date for analysis (optional)
    
    **Response includes:**
    - Custom analytics data
    - Date range information
    - Success status
    """
    try:
        logger.info("🔍 Getting custom analytics for date range")
        
        # Get analytics service
        analytics_service = get_revenue_analytics_service()
        
        # Get platform summary for custom date range
        result = await analytics_service.get_platform_revenue_summary(
            request.start_date, 
            request.end_date
        )
        
        if result["success"]:
            logger.info("✅ Custom analytics retrieved successfully")
            return create_response(
                status_code=status.HTTP_200_OK,
                status="success",
                message="Custom analytics retrieved successfully",
                data=result["data"]
            )
        else:
            logger.warning(f"❌ Failed to get custom analytics: {result.get('error', 'Unknown error')}")
            return create_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                status="error",
                message=result.get("error", "Failed to get custom analytics"),
                data=None
            )
            
    except Exception as e:
        logger.error(f"💥 Unexpected error getting custom analytics: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Internal server error: {str(e)}",
            data=None
        )
