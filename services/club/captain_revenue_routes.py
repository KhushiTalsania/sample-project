"""
Captain Revenue Routes

API routes for captain revenue analytics and statistics.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from typing import Dict, Any, Optional
import logging
import csv
import io
from datetime import datetime

from .captain_revenue_service import get_captain_revenue_service
from .auth import get_current_captain
from .models import (
    CaptainRevenueResponse, 
    CaptainMonthlyRevenueResponse, 
    CaptainClubBreakdownResponse,
    RecentEarningsResponse,
    RecentEarningsFilters,
    MonthwiseRevenueResponse
)

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["Captain Revenue"])

@router.get("/comprehensive-stats", response_model=CaptainRevenueResponse)
async def get_captain_comprehensive_stats(
    current_captain: dict = Depends(get_current_captain)
):
    """
    Get comprehensive revenue and statistics for the current captain
    
    This endpoint provides:
    - Total revenue earned from all clubs (95% of total revenue)
    - Platform fees (5% of total revenue) 
    - Total active members across all clubs
    - Average revenue per active member
    - Total approved clubs created
    - Total content created (strategy + training + partner links)
    - Total partner links created
    
    Returns:
        CaptainRevenueResponse: Comprehensive captain statistics
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"📊 Getting comprehensive stats for captain: {captain_id}")
        
        service = get_captain_revenue_service()
        result = await service.get_captain_comprehensive_stats(captain_id)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get captain stats: {result.get('error', 'Unknown error')}"
            )
        
        logger.info(f"✅ Comprehensive stats retrieved for captain {captain_id}")
        return result["data"]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting comprehensive captain stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting captain stats: {str(e)}"
        )

@router.get("/monthly-breakdown", response_model=CaptainMonthlyRevenueResponse)
async def get_captain_monthly_revenue(
    months: int = 12,
    current_captain: dict = Depends(get_current_captain)
):
    """
    Get captain's monthly revenue breakdown
    
    Args:
        months: Number of months to analyze (default: 12, max: 24)
        
    Returns:
        CaptainMonthlyRevenueResponse: Monthly revenue data
    """
    try:
        # Validate months parameter
        if months < 1 or months > 24:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Months must be between 1 and 24"
            )
        
        captain_id = current_captain["user_id"]
        logger.info(f"📈 Getting monthly revenue for captain: {captain_id} for {months} months")
        
        service = get_captain_revenue_service()
        result = await service.get_captain_monthly_revenue(captain_id, months)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get monthly revenue: {result.get('error', 'Unknown error')}"
            )
        
        logger.info(f"✅ Monthly revenue data retrieved for captain {captain_id}")
        return {"data": result["data"], "months_analyzed": months}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting monthly revenue: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting monthly revenue: {str(e)}"
        )

@router.get("/club-breakdown", response_model=CaptainClubBreakdownResponse)
async def get_captain_club_breakdown(
    current_captain: dict = Depends(get_current_captain)
):
    """
    Get detailed breakdown of captain's clubs with revenue and member data
    
    This endpoint provides per-club statistics including:
    - Revenue data (earnings, platform fees, total revenue)
    - Member counts (total, paid, trial)
    - Content counts (strategy videos, training videos, partner links)
    - Club status and creation date
    
    Returns:
        CaptainClubBreakdownResponse: Detailed club breakdown data
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"🏢 Getting club breakdown for captain: {captain_id}")
        
        service = get_captain_revenue_service()
        result = await service.get_captain_club_breakdown(captain_id)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get club breakdown: {result.get('error', 'Unknown error')}"
            )
        
        logger.info(f"✅ Club breakdown retrieved for captain {captain_id}: {len(result['data'])} clubs")
        return {"data": result["data"], "total_clubs": len(result["data"])}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting club breakdown: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting club breakdown: {str(e)}"
        )

@router.get("/summary")
async def get_captain_revenue_summary(
    current_captain: dict = Depends(get_current_captain)
):
    """
    Get a quick summary of captain's key revenue metrics
    
    This is a lightweight endpoint for dashboard widgets that provides:
    - Total earnings
    - Total active members
    - Total approved clubs
    - Total content created
    
    Returns:
        Dict: Quick summary of key metrics
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"📋 Getting revenue summary for captain: {captain_id}")
        
        service = get_captain_revenue_service()
        result = await service.get_captain_comprehensive_stats(captain_id)
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get revenue summary: {result.get('error', 'Unknown error')}"
            )
        
        # Extract key metrics for summary
        data = result["data"]
        summary = {
            "captain_id": captain_id,
            "total_revenue_earned": data["total_revenue_earned"],
            "platform_fees": data["platform_fees"],
            "total_active_members": data["total_active_members"],
            "total_approved_clubs": data["total_approved_clubs"],
            "total_content_created": data["total_content_created"],
            "total_partner_links": data["total_partner_links"],
            "average_revenue_per_member": data["average_revenue_per_member"],
            "generated_at": data["generated_at"]
        }
        
        logger.info(f"✅ Revenue summary retrieved for captain {captain_id}")
        return summary
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting revenue summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting revenue summary: {str(e)}"
        )


@router.get("/recent-earnings", response_model=RecentEarningsResponse)
async def get_recent_earnings(
    page: int = 1,
    limit: int = 20,
    club_id: Optional[str] = None,
    search: Optional[str] = None,
    membership_type: Optional[str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    current_captain: dict = Depends(get_current_captain)
):
    """
    Get recent earnings data for captain with pagination and filters
    
    This endpoint provides detailed earnings information for all members across
    all clubs created by the captain, including both trial and paid members.
    
    **Features:**
    - Pagination support (page, limit)
    - Club-wise filtering
    - Search by club name or member name
    - Filter by membership type (trial, paid)
    - Month/year filtering
    - Multiple sorting options
    - Real-time revenue calculations
    
    **Parameters:**
    - **page**: Page number (default: 1)
    - **limit**: Items per page (default: 20, max: 100)
    - **club_id**: Filter by specific club ID
    - **search**: Search by club name or member full name
    - **membership_type**: Filter by membership type (trial, paid)
    - **month**: Filter by month (1-12)
    - **year**: Filter by year
    - **sort_by**: Sort field (created_at, amount_paid, full_name, club_name)
    - **sort_order**: Sort order (asc, desc)
    
    **Response includes:**
    - List of member earnings with detailed information
    - Pagination metadata
    - Applied filters
    - Summary statistics (total earnings, member counts)
    
    **Member Data includes:**
    - User details (name, avatar)
    - Club information (name, ID)
    - Membership details (type, plan, status)
    - Payment information (amount, fees, captain share)
    - Join dates and timestamps
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"📊 Getting recent earnings for captain: {captain_id}")
        
        # Build filters
        filters = {
            "page": page,
            "limit": limit,
            "club_id": club_id,
            "search": search,
            "membership_type": membership_type,
            "month": month,
            "year": year,
            "sort_by": sort_by,
            "sort_order": sort_order
        }
        
        # Get captain revenue service
        revenue_service = get_captain_revenue_service()
        
        # Get recent earnings data
        result = await revenue_service.get_recent_earnings(captain_id, filters)
        
        if not result.get("success", False):
            logger.error(f"❌ Error getting recent earnings: {result.get('error', 'Unknown error')}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to get recent earnings")
            )
        
        logger.info(f"✅ Recent earnings retrieved successfully for captain: {captain_id}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"💥 Unexpected error getting recent earnings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/recent-earnings/export-csv")
async def export_recent_earnings_csv(
    club_id: Optional[str] = None,
    search: Optional[str] = None,
    membership_type: Optional[str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    current_captain: dict = Depends(get_current_captain)
):
    """
    Export recent earnings data as CSV file
    
    This endpoint exports the same data as the recent earnings API but in CSV format
    for easy analysis in spreadsheet applications.
    
    **Features:**
    - Same filtering options as recent earnings API
    - CSV format for easy data analysis
    - All member earnings data included
    - No pagination (exports all matching records)
    
    **Parameters:**
    - **club_id**: Filter by specific club ID
    - **search**: Search by club name or member full name
    - **membership_type**: Filter by membership type (trial, paid)
    - **month**: Filter by month (1-12)
    - **year**: Filter by year
    - **sort_by**: Sort field (created_at, amount_paid, full_name, club_name)
    - **sort_order**: Sort order (asc, desc)
    
    **CSV Columns:**
    - Full Name, Club Name
    - Membership Type, Pricing Plan, Membership Status
    - Payment Method, Amount Paid, Platform Fee, Your Share
    - Join Date
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"📊 Exporting recent earnings CSV for captain: {captain_id}")
        
        # Build filters (no pagination for CSV export)
        filters = {
            "page": 1,
            "limit": 10000,  # Large limit to get all records
            "club_id": club_id,
            "search": search,
            "membership_type": membership_type,
            "month": month,
            "year": year,
            "sort_by": sort_by,
            "sort_order": sort_order
        }
        
        # Get captain revenue service
        revenue_service = get_captain_revenue_service()
        
        # Get recent earnings data
        result = await revenue_service.get_recent_earnings(captain_id, filters)
        
        if not result.get("success", False):
            logger.error(f"❌ Error getting recent earnings for CSV: {result.get('error', 'Unknown error')}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to get recent earnings data")
            )
        
        # Prepare CSV data
        members_data = result.get("data", [])
        
        if not members_data:
            logger.info(f"📊 No earnings data found for captain: {captain_id}")
            # Return empty CSV with headers
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write headers with user-friendly names (removed user_id, avatar_url, club_id, club_url, payment_status, created_at)
            headers = [
                "Full Name", "Club Name",
                "Membership Type", "Pricing Plan", "Membership Status",
                "Payment Method", "Amount Paid", "Platform Fee", "Your Share",
                "Join Date"
            ]
            writer.writerow(headers)
            
            output.seek(0)
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8')),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=recent_earnings_empty.csv"}
            )
        
        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers with user-friendly names (removed user_id, avatar_url, club_id, club_url, payment_status, created_at)
        headers = [
            "Full Name", "Club Name",
            "Membership Type", "Pricing Plan", "Membership Status",
            "Payment Method", "Amount Paid", "Your Share",
            "Join Date"
        ]
        writer.writerow(headers)
        print(members_data,"members_data")
        # Write data rows (removed user_id, avatar_url, club_id, club_name_based_id, status, created_at)
        for member in members_data:
            # Handle join_date - it can be a datetime object or a string
            join_date = member.get("join_date", "")
            if join_date:
                if isinstance(join_date, str):
                    # Parse string to datetime first, then format
                    try:
                        join_date_obj = datetime.fromisoformat(join_date.replace('Z', '+00:00'))
                        join_date_formatted = join_date_obj.strftime("%m/%d/%Y")
                    except:
                        join_date_formatted = join_date  # Use as-is if parsing fails
                else:
                    # Already a datetime object
                    join_date_formatted = join_date.strftime("%m/%d/%Y")
            else:
                join_date_formatted = ""
            
            row = [
                member.get("full_name", ""),
                member.get("club_name", ""),
                member.get("membership_type", "").capitalize(),
                member.get("pricing_plan", "").capitalize(),
                member.get("membership_status", "").capitalize(),
               "Card",
                member.get("amount_paid", 0.0),
                # member.get("platform_fee", 0.0),
                member.get("your_share", 0.0),
                join_date_formatted
            ]
            writer.writerow(row)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recent_earnings_{captain_id}_{timestamp}.csv"
        
        # Prepare response
        output.seek(0)
        csv_content = output.getvalue()
        
        logger.info(f"✅ CSV export completed for captain {captain_id}: {len(members_data)} records")
        
        return StreamingResponse(
            io.BytesIO(csv_content.encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"💥 Unexpected error exporting CSV: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/monthwise-revenue", response_model=MonthwiseRevenueResponse)
async def get_monthwise_revenue(
    year: Optional[int] = None,
    month: Optional[int] = None,
    page: int = 1,
    limit: int = 12,
    current_captain: dict = Depends(get_current_captain)
):
    """
    Get month-wise revenue breakdown showing old vs new customers
    
    This endpoint provides detailed monthly revenue analysis categorizing earnings
    into "old customers" (joined before current month) and "new customers" 
    (joined in current month) based on member join dates.
    
    **Features:**
    - Monthly revenue breakdown for all months
    - Old vs New customer categorization
    - Stripe Connect integration for real-time data
    - Historical revenue tracking
    
    **Parameters:**
    - **year**: Filter by specific year (default: current year)
    - **month**: Filter by specific month (1-12, default: all months)
    - **page**: Page number for pagination (default: 1)
    - **limit**: Number of months per page (default: 12, max: 12)
    
    **Response includes:**
    - Monthly revenue data with old/new customer breakdown
    - Total revenue for each month
    - Customer counts and percentages
    - Revenue trends and analysis
    - Pagination metadata
    
    **Customer Classification:**
    - **New Customer**: Member joined in the current month
    - **Old Customer**: Member joined before the current month
    - **Revenue Flow**: New customer revenue in month X becomes old customer revenue in month X+1
    """
    try:
        captain_id = current_captain["user_id"]
        logger.info(f"📊 Getting month-wise revenue for captain: {captain_id}")
        
        # Get captain revenue service
        revenue_service = get_captain_revenue_service()
        
        # Get month-wise revenue data
        result = await revenue_service.get_monthwise_revenue(captain_id, year, month, page, limit)
        
        if not result.get("success", False):
            logger.error(f"❌ Error getting month-wise revenue: {result.get('error', 'Unknown error')}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to get month-wise revenue")
            )
        
        logger.info(f"✅ Month-wise revenue retrieved successfully for captain: {captain_id}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"💥 Unexpected error getting month-wise revenue: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
