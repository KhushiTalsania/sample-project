"""
Captain Revenue Service

This service provides comprehensive revenue analytics and statistics for captains,
including total earnings, platform fees, active members, content statistics, and more.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from .db import get_club_collection, get_user_collection, get_membership_collection
from .datetime_utils import safe_datetime_serialize

# Configure logging
logger = logging.getLogger(__name__)

class CaptainRevenueService:
    """Service for captain revenue analytics and statistics"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
        self.membership_collection = get_membership_collection()
        self.revenue_collection = self.club_collection.database['revenue_tracking']
        self.hub_collection = self.club_collection.database['hubs']
        self.payments_collection = self.club_collection.database['club_payments']
        self.picks_collection = self.club_collection.database['club_picks']
        
        # Import Stripe for real-time balance fetching
        import stripe
        import os
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        self.stripe = stripe
    
    async def get_captain_comprehensive_stats(self, captain_id: str) -> Dict[str, Any]:
        """
        Get comprehensive revenue and statistics for a captain
        
        This includes:
        - Total revenue earned from all clubs (95% of total revenue)
        - Platform fees (5% of total revenue)
        - Total active members across all clubs
        - Average revenue per active member
        - Total approved clubs created
        - Total content created (strategy + training + partner links)
        - Total partner links created
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            Dict with comprehensive captain statistics
        """
        try:
            logger.info(f"📊 Getting comprehensive stats for captain: {captain_id}")
            
            # Get all data in parallel for optimization
            revenue_data, club_data, content_data, member_data, betting_data = await self._get_captain_data_parallel(captain_id)
            
            # Calculate comprehensive statistics
            stats = {
                "captain_id": captain_id,
                "generated_at": safe_datetime_serialize(datetime.utcnow()),
                
                # Revenue metrics
                "total_revenue_earned": revenue_data["total_captain_earnings"],
                "platform_fees": revenue_data["total_platform_fees"],
                "total_revenue_generated": revenue_data["total_revenue"],
                "available_balance": revenue_data.get("available_balance"),
                # "revenue_breakdown": {
                #     "captain_percentage": 95.0,
                #     "platform_percentage": 5.0,
                #     "captain_amount": revenue_data["total_captain_earnings"],
                #     "platform_amount": revenue_data["total_platform_fees"]
                # },
                
                # Club metrics
                "total_approved_clubs": club_data["approved_clubs_count"],
                "total_clubs_created": club_data["total_clubs_count"],
                "club_status_breakdown": {
                    "approved": club_data["approved_clubs_count"],
                    "pending": club_data["pending_clubs_count"],
                    "rejected": club_data["rejected_clubs_count"],
                    "total": club_data["total_clubs_count"]
                },
                
                # Member metrics
                "total_active_members": member_data["total_active_members"],
                "average_revenue_per_member": self._calculate_avg_revenue_per_member(
                    revenue_data["total_captain_earnings"], 
                    member_data["paid_members"]
                ),
                "member_breakdown": {
                    "active_members": member_data["total_active_members"],
                    "paid_members": member_data["paid_members"],
                    "trial_members": member_data["trial_members"]
                },
                
                # Content metrics
                "total_content_created": content_data["total_content"],
                "content_breakdown": {
                    "strategy_videos": content_data["strategy_videos_count"],
                    "training_videos": content_data["training_videos_count"],
                    "partner_links": content_data["partner_links_count"],
                    "total": content_data["total_content"]
                },
                "total_partner_links": content_data["partner_links_count"],
                
                # Performance metrics
                "average_club_revenue": self._calculate_avg_club_revenue(
                    revenue_data["total_captain_earnings"], 
                    club_data["approved_clubs_count"]
                ),
                "revenue_per_content": self._calculate_revenue_per_content(
                    revenue_data["total_captain_earnings"], 
                    content_data["total_content"]
                ),
                
                # Betting performance metrics
                "total_picks": betting_data["total_picks"],
                "completed_picks": betting_data["completed_picks"],
                "winning_picks": betting_data["winning_picks"],
                "losing_picks": betting_data["losing_picks"],
                "win_percentage": betting_data["win_percentage"],
                "loss_percentage": betting_data["loss_percentage"],
                "pending_picks": betting_data["pending_picks"]
            }
            
            logger.info(f"✅ Comprehensive stats generated for captain {captain_id}")
            return {"success": True, "data": stats}
            
        except Exception as e:
            logger.error(f"❌ Error getting comprehensive captain stats: {e}")
            return {"success": False, "error": str(e)}
    
    async def _get_captain_data_parallel(self, captain_id: str) -> Tuple[Dict, Dict, Dict, Dict, Dict]:
        """Get all captain data in parallel for optimization"""
        try:
            # Create tasks for parallel execution
            import asyncio
            
            revenue_task = self._get_captain_revenue_data(captain_id)
            club_task = self._get_captain_club_data(captain_id)
            content_task = self._get_captain_content_data(captain_id)
            member_task = self._get_captain_member_data(captain_id)
            betting_task = self._get_captain_betting_performance(captain_id)
            
            # Execute all tasks in parallel
            revenue_data, club_data, content_data, member_data, betting_data = await asyncio.gather(
                revenue_task, club_task, content_task, member_task, betting_task
            )
            
            return revenue_data, club_data, content_data, member_data, betting_data
            
        except Exception as e:
            logger.error(f"❌ Error getting captain data in parallel: {e}")
            # Return empty data structures on error
            return (
                {"total_captain_earnings": 0, "total_platform_fees": 0, "total_revenue": 0},
                {"approved_clubs_count": 0, "total_clubs_count": 0, "pending_clubs_count": 0, "rejected_clubs_count": 0},
                {"total_content": 0, "strategy_videos_count": 0, "training_videos_count": 0, "partner_links_count": 0},
                {"total_active_members": 0, "paid_members": 0, "trial_members": 0},
                {"total_picks": 0, "completed_picks": 0, "winning_picks": 0, "losing_picks": 0, "win_percentage": 0.0, "loss_percentage": 0.0, "pending_picks": 0}
            )
    
    async def _get_captain_revenue_data(self, captain_id: str) -> Dict[str, Any]:
        """Get captain's revenue data from Stripe Connect, revenue tracking, and club payments"""
        try:
            # Validate captain_id format
            if not ObjectId.is_valid(captain_id):
                logger.error(f"❌ Invalid captain_id format: {captain_id}")
                return {
                    "total_captain_earnings": 0,
                    "total_platform_fees": 0,
                    "total_revenue": 0,
                    "transaction_count": 0
                }
            
            # First try to get real-time data from Stripe Connect
            stripe_revenue = await self._get_stripe_connect_revenue(captain_id)
            if stripe_revenue["total_revenue"] > 0:
                logger.info(f"💰 Found revenue from Stripe Connect: ${stripe_revenue['total_revenue']}")
                return stripe_revenue
            
            # If no Stripe Connect data, try revenue_tracking collection
            revenue_pipeline = [
                {
                    "$match": {
                        "captain_id": ObjectId(captain_id),
                        "status": "completed"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_captain_earnings": {"$sum": "$captain_amount"},
                        "total_platform_fees": {"$sum": "$platform_fee"},
                        "total_revenue": {"$sum": "$total_amount"},
                        "transaction_count": {"$sum": 1}
                    }
                }
            ]
            
            revenue_result = await self.revenue_collection.aggregate(revenue_pipeline).to_list(None)
            
            if revenue_result and revenue_result[0]["total_revenue"] > 0:
                return {
                    "total_captain_earnings": revenue_result[0]["total_captain_earnings"],
                    "total_platform_fees": revenue_result[0]["total_platform_fees"],
                    "total_revenue": revenue_result[0]["total_revenue"],
                    "transaction_count": revenue_result[0]["transaction_count"]
                }
            
            # If no revenue_tracking data, try club_payments collection
            logger.info(f"🔍 No revenue_tracking data found, checking club_payments for captain: {captain_id}")
            
            # Get all clubs created by this captain
            clubs = await self.club_collection.find({
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}
            }, {"_id": 1}).to_list(None)
            
            if not clubs:
                return {
                    "total_captain_earnings": 0,
                    "total_platform_fees": 0,
                    "total_revenue": 0,
                    "transaction_count": 0
                }
            
            club_ids = [str(club["_id"]) for club in clubs]
            
            # Get payments for captain's clubs
            payments_pipeline = [
                {
                    "$match": {
                        "club_id": {"$in": club_ids},
                        "status": "succeeded"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_revenue": {"$sum": "$amount"},
                        "transaction_count": {"$sum": 1}
                    }
                }
            ]
            
            payments_result = await self.payments_collection.aggregate(payments_pipeline).to_list(None)
            
            if payments_result:
                total_revenue = payments_result[0]["total_revenue"]
                transaction_count = payments_result[0]["transaction_count"]
                
                # Calculate 95/5 split
                captain_earnings = total_revenue * 0.95
                platform_fees = total_revenue * 0.05
                
                logger.info(f"💰 Found revenue in club_payments: ${total_revenue} (Captain: ${captain_earnings}, Platform: ${platform_fees})")
                
                return {
                    "total_captain_earnings": captain_earnings,
                    "total_platform_fees": platform_fees,
                    "total_revenue": total_revenue,
                    "transaction_count": transaction_count
                }
            else:
                return {
                    "total_captain_earnings": 0,
                    "total_platform_fees": 0,
                    "total_revenue": 0,
                    "transaction_count": 0
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting captain revenue data: {e}")
            return {
                "total_captain_earnings": 0,
                "total_platform_fees": 0,
                "total_revenue": 0,
                "transaction_count": 0
            }
    
    async def _get_stripe_connect_revenue(self, captain_id: str) -> Dict[str, Any]:
        """Get captain's revenue data directly from Stripe Connect account"""
        try:
            # Get captain's Stripe Connect account ID from users table
            captain = await self.user_collection.find_one({"_id": ObjectId(captain_id)})
            
            if not captain:
                logger.error(f"❌ Captain not found: {captain_id}")
                return {
                    "total_captain_earnings": 0,
                    "total_platform_fees": 0,
                    "total_revenue": 0,
                    "transaction_count": 0
                }
            
            stripe_connect_account_id = captain.get("stripe_connect_account_id")
            
            if not stripe_connect_account_id:
                logger.info(f"🔍 Captain {captain_id} has no Stripe Connect account ID")
                return {
                    "total_captain_earnings": 0,
                    "total_platform_fees": 0,
                    "total_revenue": 0,
                    "transaction_count": 0
                }
            
            logger.info(f"🔍 Getting Stripe Connect data for account: {stripe_connect_account_id}")
            
            # Get account balance from Stripe
            balance = self.stripe.Balance.retrieve(stripe_account=stripe_connect_account_id)
            
            # Get total charges (revenue) from Stripe
            charges = self.stripe.Charge.list(
                stripe_account=stripe_connect_account_id,
                limit=100  # Get more charges for accurate total
            )
            
            # Calculate total revenue from charges
            total_revenue = 0
            transaction_count = 0
            
            for charge in charges.data:
                if charge.status == "succeeded":
                    total_revenue += charge.amount / 100  # Convert from cents to dollars
                    transaction_count += 1
            
            # If we have more charges, get all of them
            while charges.has_more:
                charges = self.stripe.Charge.list(
                    stripe_account=stripe_connect_account_id,
                    starting_after=charges.data[-1].id,
                    limit=100
                )
                for charge in charges.data:
                    if charge.status == "succeeded":
                        total_revenue += charge.amount / 100
                        transaction_count += 1
            
            # Calculate 95/5 split
            captain_earnings = total_revenue * 0.95
            platform_fees = total_revenue * 0.05
            
            # Get available balance (what captain can withdraw)
            available_balance = 0
            for balance_item in balance.available:
                available_balance += balance_item.amount / 100
            
            logger.info(f"💰 Stripe Connect Revenue - Total: ${total_revenue:.2f}, Captain: ${captain_earnings:.2f}, Platform: ${platform_fees:.2f}, Available: ${available_balance:.2f}")
            
            return {
                "total_captain_earnings": round(captain_earnings, 2),
                "total_platform_fees": round(platform_fees, 2),
                "total_revenue": round(total_revenue, 2),
                "transaction_count": transaction_count,
                "available_balance": round(available_balance, 2)  # Additional info
            }
            
        except self.stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error getting Connect revenue: {e}")
            return {
                "total_captain_earnings": 0,
                "total_platform_fees": 0,
                "total_revenue": 0,
                "transaction_count": 0
            }
        except Exception as e:
            logger.error(f"❌ Error getting Stripe Connect revenue: {e}")
            return {
                "total_captain_earnings": 0,
                "total_platform_fees": 0,
                "total_revenue": 0,
                "transaction_count": 0
            }
    
    async def _get_captain_club_data(self, captain_id: str) -> Dict[str, Any]:
        """Get captain's club data and statistics"""
        try:
            # Validate captain_id format
            if not ObjectId.is_valid(captain_id):
                logger.error(f"❌ Invalid captain_id format: {captain_id}")
                return {
                    "total_clubs_count": 0,
                    "approved_clubs_count": 0,
                    "pending_clubs_count": 0,
                    "rejected_clubs_count": 0
                }
            
            # Get all clubs created by this captain
            clubs = await self.club_collection.find({
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}  # Exclude permanently deleted clubs
            }).to_list(None)
            
            total_clubs = len(clubs)
            approved_clubs = len([club for club in clubs if club.get("status") == "approved"])
            pending_clubs = len([club for club in clubs if club.get("status") == "pending"])
            rejected_clubs = len([club for club in clubs if club.get("status") == "rejected"])
            
            return {
                "total_clubs_count": total_clubs,
                "approved_clubs_count": approved_clubs,
                "pending_clubs_count": pending_clubs,
                "rejected_clubs_count": rejected_clubs
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting captain club data: {e}")
            return {
                "total_clubs_count": 0,
                "approved_clubs_count": 0,
                "pending_clubs_count": 0,
                "rejected_clubs_count": 0
            }
    
    async def _get_captain_content_data(self, captain_id: str) -> Dict[str, Any]:
        """Get captain's content data from hubs collection"""
        try:
            # Validate captain_id format
            if not ObjectId.is_valid(captain_id):
                logger.error(f"❌ Invalid captain_id format: {captain_id}")
                return {
                    "total_content": 0,
                    "strategy_videos_count": 0,
                    "training_videos_count": 0,
                    "partner_links_count": 0
                }
            
            # Get content counts by section type
            pipeline = [
                {
                    "$match": {
                        "captain_id": captain_id,
                        "is_active": True
                    }
                },
                {
                    "$group": {
                        "_id": "$section",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            result = await self.hub_collection.aggregate(pipeline).to_list(None)
            
            # Initialize counts
            strategy_videos_count = 0
            training_videos_count = 0
            partner_links_count = 0
            
            # Process results
            for item in result:
                section = item["_id"]
                count = item["count"]
                
                if "strategy" in section.lower():
                    strategy_videos_count = count
                elif "training" in section.lower():
                    training_videos_count = count
                elif "partner" in section.lower():
                    partner_links_count = count
            
            total_content = strategy_videos_count + training_videos_count + partner_links_count
            
            return {
                "total_content": total_content,
                "strategy_videos_count": strategy_videos_count,
                "training_videos_count": training_videos_count,
                "partner_links_count": partner_links_count
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting captain content data: {e}")
            return {
                "total_content": 0,
                "strategy_videos_count": 0,
                "training_videos_count": 0,
                "partner_links_count": 0
            }
    
    async def _get_captain_betting_performance(self, captain_id: str) -> Dict[str, Any]:
        """Get captain's betting performance across all clubs"""
        try:
            # Validate captain_id format
            if not ObjectId.is_valid(captain_id):
                logger.error(f"❌ Invalid captain_id format: {captain_id}")
                return {
                    "total_picks": 0,
                    "completed_picks": 0,
                    "winning_picks": 0,
                    "losing_picks": 0,
                    "win_percentage": 0.0,
                    "loss_percentage": 0.0,
                    "pending_picks": 0
                }
            
            # Get all clubs created by this captain
            clubs = await self.club_collection.find({
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}
            }, {"_id": 1, "name_based_id": 1}).to_list(None)
            
            if not clubs:
                logger.info(f"🔍 No clubs found for captain: {captain_id}")
                return {
                    "total_picks": 0,
                    "completed_picks": 0,
                    "winning_picks": 0,
                    "losing_picks": 0,
                    "win_percentage": 0.0,
                    "loss_percentage": 0.0,
                    "pending_picks": 0
                }
            
            # Get club name-based IDs for querying picks
            club_name_based_ids = [club["name_based_id"] for club in clubs if club.get("name_based_id")]
            
            if not club_name_based_ids:
                logger.warning(f"⚠️ No valid club name-based IDs found for captain: {captain_id}")
                return {
                    "total_picks": 0,
                    "completed_picks": 0,
                    "winning_picks": 0,
                    "losing_picks": 0,
                    "win_percentage": 0.0,
                    "loss_percentage": 0.0,
                    "pending_picks": 0
                }
            
            # Aggregate picks data across all captain's clubs
            pipeline = [
                {
                    "$match": {
                        "club_id": {"$in": club_name_based_ids},
                        "is_active": True
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_picks": {"$sum": 1},
                        "completed_picks": {
                            "$sum": {
                                "$cond": [{"$eq": ["$status", "completed"]}, 1, 0]
                            }
                        },
                        "winning_picks": {
                            "$sum": {
                                "$cond": [
                                    {"$and": [
                                        {"$eq": ["$status", "completed"]},
                                        {"$eq": ["$result", "win"]}
                                    ]}, 1, 0
                                ]
                            }
                        },
                        "losing_picks": {
                            "$sum": {
                                "$cond": [
                                    {"$and": [
                                        {"$eq": ["$status", "completed"]},
                                        {"$eq": ["$result", "loss"]}
                                    ]}, 1, 0
                                ]
                            }
                        },
                        "pending_picks": {
                            "$sum": {
                                "$cond": [{"$eq": ["$status", "pending"]}, 1, 0]
                            }
                        }
                    }
                }
            ]
            
            result = await self.picks_collection.aggregate(pipeline).to_list(None)
            
            if not result:
                logger.info(f"🔍 No picks found for captain's clubs: {captain_id}")
                return {
                    "total_picks": 0,
                    "completed_picks": 0,
                    "winning_picks": 0,
                    "losing_picks": 0,
                    "win_percentage": 0.0,
                    "loss_percentage": 0.0,
                    "pending_picks": 0
                }
            
            stats = result[0]
            total_picks = stats.get("total_picks", 0)
            completed_picks = stats.get("completed_picks", 0)
            winning_picks = stats.get("winning_picks", 0)
            losing_picks = stats.get("losing_picks", 0)
            pending_picks = stats.get("pending_picks", 0)
            
            # Calculate percentages
            win_percentage = (winning_picks / total_picks * 100) if total_picks > 0 else 0.0
            loss_percentage = (losing_picks / completed_picks * 100) if completed_picks > 0 else 0.0
            
            logger.info(f"🎯 Betting performance for captain {captain_id}: {total_picks} total picks, {winning_picks} wins, {losing_picks} losses, {win_percentage:.2f}% win rate")
            
            return {
                "total_picks": total_picks,
                "completed_picks": completed_picks,
                "winning_picks": winning_picks,
                "losing_picks": losing_picks,
                "win_percentage": round(win_percentage, 2),
                "loss_percentage": round(loss_percentage, 2),
                "pending_picks": pending_picks
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting captain betting performance: {e}")
            return {
                "total_picks": 0,
                "completed_picks": 0,
                "winning_picks": 0,
                "losing_picks": 0,
                "win_percentage": 0.0,
                "loss_percentage": 0.0,
                "pending_picks": 0
            }
    
    async def get_monthwise_revenue(self, captain_id: str, year: Optional[int] = None, month: Optional[int] = None, page: int = 1, limit: int = 12) -> Dict[str, Any]:
        """Get month-wise revenue breakdown with old vs new customers"""
        try:
            from datetime import datetime, timedelta
            import calendar
            
            # Use current year if not specified
            if year is None:
                year = datetime.now().year
            
            # Validate month filter
            if month is not None and (month < 1 or month > 12):
                return {
                    "success": False,
                    "error": "Month must be between 1 and 12"
                }
            
            # Validate pagination
            if page < 1:
                page = 1
            if limit < 1 or limit > 12:
                limit = 12
            
            start_time = datetime.utcnow()
            logger.info(f"📊 Getting month-wise revenue for captain {captain_id}, year: {year}, month: {month}, page: {page}, limit: {limit}")
            
            # Get captain's stripe connect account ID
            captain = await self.user_collection.find_one(
                {"_id": ObjectId(captain_id)},
                {"stripe_connect_account_id": 1}
            )
            
            if not captain or not captain.get("stripe_connect_account_id"):
                logger.warning(f"⚠️ No Stripe Connect account found for captain: {captain_id}")
                return {
                    "success": True,
                    "captain_id": captain_id,
                    "year": year,
                    "monthly_data": [],
                    "summary": {
                        "total_revenue": 0.0,
                        "total_old_customers_revenue": 0.0,
                        "total_new_customers_revenue": 0.0,
                        "average_monthly_revenue": 0.0,
                        "best_month": None,
                        "worst_month": None
                    },
                    "generated_at": safe_datetime_serialize(datetime.utcnow())
                }
            
            stripe_account_id = captain["stripe_connect_account_id"]
            
            # Get all clubs created by this captain (optimized query with index)
            clubs = await self.club_collection.find({
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}
            }, {
                "_id": 1, 
                "name": 1, 
                "name_based_id": 1,
                "members": 1,
                "paid_members": 1
            }).to_list(None)
            
            if not clubs:
                logger.info(f"🔍 No clubs found for captain: {captain_id}")
                return {
                    "success": True,
                    "captain_id": captain_id,
                    "year": year,
                    "monthly_data": [],
                    "summary": {
                        "total_revenue": 0.0,
                        "total_old_customers_revenue": 0.0,
                        "total_new_customers_revenue": 0.0,
                        "average_monthly_revenue": 0.0,
                        "best_month": None,
                        "worst_month": None
                    },
                    "generated_at": safe_datetime_serialize(datetime.utcnow())
                }
            
            # Get all members from all clubs with their join dates (optimized processing)
            all_members = []
            club_mapping = {}
            
            for club in clubs:
                club_id_str = str(club["_id"])
                club_name = club.get("name", "Unknown Club")
                club_mapping[club_id_str] = club_name
                
                # Process both member types in single loop for better performance
                for member_list, membership_type in [(club.get("members", []), "trial"), (club.get("paid_members", []), "paid")]:
                    for member in member_list:
                        if member.get("is_active", True) and member.get("membership_status") == "active":
                            all_members.append({
                                "user_id": member.get("user_id"),
                                "club_id": club_id_str,
                                "club_name": club_name,
                                "join_date": member.get("join_date") or member.get("created_at") or member.get("updated_at"),
                                "amount_paid": member.get("amount_paid", 0.0) if membership_type == "paid" else 0.0,
                                "membership_type": membership_type
                            })
            
            # Get Stripe charges for the year (run in parallel with member processing)
            import asyncio
            stripe_task = asyncio.create_task(self._get_stripe_charges_for_year(stripe_account_id, year))
            
            # Process monthly data
            all_monthly_data = []
            total_revenue = 0.0
            total_old_revenue = 0.0
            total_new_revenue = 0.0
            
            # Create optimized mappings for faster lookups
            member_join_dates = {}
            member_amounts = {}
            
            # Pre-process member data for faster lookups
            for member in all_members:
                user_id = member["user_id"]
                if user_id and member["join_date"]:
                    try:
                        if isinstance(member["join_date"], str):
                            join_date = datetime.fromisoformat(member["join_date"].replace('Z', '+00:00'))
                        else:
                            join_date = member["join_date"]
                        member_join_dates[user_id] = join_date
                        member_amounts[user_id] = member["amount_paid"]
                    except Exception as e:
                        logger.warning(f"⚠️ Error parsing join date for member {user_id}: {e}")
                        continue
            
            # Wait for Stripe data
            stripe_charges = await stripe_task
            
            # Determine which months to process (early optimization)
            if month is not None:
                months_to_process = [month]
            else:
                months_to_process = list(range(1, 13))
            
            # Early return if no data
            if not all_members and not stripe_charges:
                logger.info(f"🔍 No members or charges found for captain {captain_id}")
                return {
                    "success": True,
                    "captain_id": captain_id,
                    "year": year,
                    "monthly_data": [],
                    "summary": {
                        "total_revenue": 0.0,
                        "total_old_customers_revenue": 0.0,
                        "total_new_customers_revenue": 0.0,
                        "average_monthly_revenue": 0.0,
                        "best_month": None,
                        "worst_month": None
                    },
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total_months": 0,
                        "total_pages": 0,
                        "has_next": False,
                        "has_prev": False
                    },
                    "filters": {
                        "year": year,
                        "month": month,
                        "page": page,
                        "limit": limit
                    },
                    "generated_at": safe_datetime_serialize(datetime.utcnow())
                }
            
            # Track revenue from new customers that becomes old customer revenue in next month
            new_customer_revenue_by_month = {}
            
            # Pre-filter charges by month for better performance
            charges_by_month = {}
            for charge in stripe_charges:
                charge_month = charge["created"].month
                if charge_month not in charges_by_month:
                    charges_by_month[charge_month] = []
                charges_by_month[charge_month].append(charge)
            
            for month_num in months_to_process:
                month_name = calendar.month_name[month_num]
                month_start = datetime(year, month_num, 1)
                month_end = datetime(year, month_num + 1, 1) if month_num < 12 else datetime(year + 1, 1, 1)
                
                # Get charges for this month (optimized lookup)
                month_charges = charges_by_month.get(month_num, [])
                month_revenue = sum(charge["amount"] * 0.95 for charge in month_charges)  # 95% to captain
                
                # Categorize revenue based on member join dates
                old_customers_revenue = 0.0
                new_customers_revenue = 0.0
                old_customers_count = 0
                new_customers_count = 0
                
                # Categorize members for this month (optimized with pre-computed data)
                old_customers_for_month = []
                new_customers_for_month = []
                
                # Use pre-computed member data for faster processing
                for user_id, join_date in member_join_dates.items():
                    if join_date < month_start:
                        # Old customer - joined before this month
                        old_customers_for_month.append({
                            "user_id": user_id,
                            "amount_paid": member_amounts.get(user_id, 0.0)
                        })
                    elif month_start <= join_date < month_end:
                        # New customer - joined in this month
                        new_customers_for_month.append({
                            "user_id": user_id,
                            "amount_paid": member_amounts.get(user_id, 0.0)
                        })
                
                # Calculate revenue from old vs new customers (optimized matching)
                # Create amount lookup sets for faster matching
                new_customer_amounts = {member["amount_paid"] for member in new_customers_for_month if member["amount_paid"] > 0}
                old_customer_amounts = {member["amount_paid"] for member in old_customers_for_month if member["amount_paid"] > 0}
                
                for charge in month_charges:
                    charge_amount = charge["amount"]
                    charge_revenue = charge_amount * 0.95  # 95% to captain
                    
                    # Fast lookup for matching amounts
                    matched = False
                    
                    # First try to match with new customers (prioritize new signups)
                    if charge_amount in new_customer_amounts:
                        new_customers_revenue += charge_revenue
                        new_customers_count += 1
                        matched = True
                    # If not matched with new customers, try old customers
                    elif charge_amount in old_customer_amounts:
                        old_customers_revenue += charge_revenue
                        old_customers_count += 1
                        matched = True
                    
                    # If still not matched, distribute based on customer counts
                    if not matched:
                        total_customers_this_month = len(old_customers_for_month) + len(new_customers_for_month)
                        if total_customers_this_month > 0:
                            if len(new_customers_for_month) > 0:
                                new_customers_revenue += charge_revenue
                                new_customers_count += 1
                            elif len(old_customers_for_month) > 0:
                                old_customers_revenue += charge_revenue
                                old_customers_count += 1
                        else:
                            # No customers found, assume new customer (new signup)
                            new_customers_revenue += charge_revenue
                            new_customers_count += 1
                
                # Add revenue from previous month's new customers (now old customers)
                if month_num > 1:
                    prev_month_key = f"{year}-{month_num-1:02d}"
                    if prev_month_key in new_customer_revenue_by_month:
                        old_customers_revenue += new_customer_revenue_by_month[prev_month_key]
                        old_customers_count += 1  # Approximate count
                
                # Store this month's new customer revenue for next month
                if new_customers_revenue > 0:
                    current_month_key = f"{year}-{month_num:02d}"
                    new_customer_revenue_by_month[current_month_key] = new_customers_revenue
                
                # Calculate percentages
                old_percentage = (old_customers_revenue / month_revenue * 100) if month_revenue > 0 else 0.0
                new_percentage = (new_customers_revenue / month_revenue * 100) if month_revenue > 0 else 0.0
                
                all_monthly_data.append({
                    "month": month_num,
                    "month_name": month_name,
                    "year": year,
                    "total_revenue": round(month_revenue, 2),
                    "old_customers_revenue": round(old_customers_revenue, 2),
                    "new_customers_revenue": round(new_customers_revenue, 2),
                    "total_customers": old_customers_count + new_customers_count
                })
                
                total_revenue += month_revenue
                total_old_revenue += old_customers_revenue
                total_new_revenue += new_customers_revenue
            
            # Apply pagination
            start_index = (page - 1) * limit
            end_index = start_index + limit
            monthly_data = all_monthly_data[start_index:end_index]
            
            # Calculate pagination info
            total_months = len(all_monthly_data)
            total_pages = (total_months + limit - 1) // limit
            has_next = page < total_pages
            has_prev = page > 1
            
            # Calculate summary
            best_month = max(monthly_data, key=lambda x: x["total_revenue"]) if monthly_data else None
            worst_month = min(monthly_data, key=lambda x: x["total_revenue"]) if monthly_data else None
            
            summary = {
                "total_revenue": round(total_revenue, 2),
                "total_old_customers_revenue": round(total_old_revenue, 2),
                "total_new_customers_revenue": round(total_new_revenue, 2),
                "average_monthly_revenue": round(total_revenue / 12, 2),
                "best_month": best_month["month_name"] if best_month else None,
                "worst_month": worst_month["month_name"] if worst_month else None
            }
            
            end_time = datetime.utcnow()
            processing_time = (end_time - start_time).total_seconds()
            logger.info(f"✅ Month-wise revenue calculated for captain {captain_id}: ${total_revenue} total, ${total_old_revenue} from old customers, ${total_new_revenue} from new customers (processed in {processing_time:.2f}s)")
            
            return {
                "success": True,
                "captain_id": captain_id,
                "year": year,
                "monthly_data": monthly_data,
                "summary": summary,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total_months": total_months,
                    "total_pages": total_pages,
                    "has_next": has_next,
                    "has_prev": has_prev
                },
                "filters": {
                    "year": year,
                    "month": month,
                    "page": page,
                    "limit": limit
                },
                "generated_at": safe_datetime_serialize(datetime.utcnow())
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting month-wise revenue: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _get_stripe_charges_for_year(self, stripe_account_id: str, year: int) -> List[Dict]:
        """Get Stripe charges for a specific year (optimized)"""
        try:
            from datetime import datetime
            
            # Calculate year boundaries
            year_start = datetime(year, 1, 1)
            year_end = datetime(year + 1, 1, 1)
            
            # Get charges from Stripe with optimized parameters
            charges = self.stripe.Charge.list(
                created={
                    'gte': int(year_start.timestamp()),
                    'lt': int(year_end.timestamp())
                },
                limit=100,  # Reasonable limit for performance
                expand=['data']  # Expand data for faster access
            )
            
            # Optimized filtering and conversion
            account_charges = []
            for charge in charges.data:
                # Quick filter checks first
                if (charge.get('destination') == stripe_account_id and 
                    charge.status == 'succeeded' and 
                    charge.amount > 0):
                    
                    account_charges.append({
                        'id': charge.id,
                        'amount': charge.amount / 100,  # Convert from cents
                        'created': datetime.fromtimestamp(charge.created),
                        'currency': charge.currency,
                        'description': charge.description
                    })
            
            logger.info(f"🔍 Found {len(account_charges)} Stripe charges for account {stripe_account_id} in {year}")
            return account_charges
            
        except Exception as e:
            logger.error(f"❌ Error getting Stripe charges for year {year}: {e}")
            return []
    
    async def _get_captain_member_data(self, captain_id: str) -> Dict[str, Any]:
        """Get captain's member data across all clubs"""
        try:
            # Validate captain_id format
            if not ObjectId.is_valid(captain_id):
                logger.error(f"❌ Invalid captain_id format: {captain_id}")
                return {
                    "total_active_members": 0,
                    "paid_members": 0,
                    "trial_members": 0
                }
            
            # Get all clubs created by this captain with member data
            clubs = await self.club_collection.find({
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}
            }, {
                "_id": 1, 
                "name": 1, 
                "members": 1, 
                "paid_members": 1
            }).to_list(None)
            
            if not clubs:
                return {
                    "total_active_members": 0,
                    "paid_members": 0,
                    "trial_members": 0
                }
            
            # Count members from both arrays in clubs
            paid_members = 0
            trial_members = 0
            
            for club in clubs:
                # Count paid members (from paid_members array)
                paid_members_list = club.get("paid_members", [])
                for member in paid_members_list:
                    if member.get("is_active", True) and member.get("membership_status") == "active":
                        paid_members += 1
                
                # Count trial members (from members array)
                members_list = club.get("members", [])
                for member in members_list:
                    if member.get("is_active", True) and member.get("membership_status") == "active":
                        trial_members += 1
            
            total_active_members = paid_members + trial_members
            
            return {
                "total_active_members": total_active_members,
                "paid_members": paid_members,
                "trial_members": trial_members
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting captain member data: {e}")
            return {
                "total_active_members": 0,
                "paid_members": 0,
                "trial_members": 0
            }
    
    def _calculate_avg_revenue_per_member(self, total_revenue: float, paid_members: int) -> float:
        """Calculate average revenue per paid member"""
        if paid_members > 0:
            return round(total_revenue / paid_members, 2)
        return 0.0
    
    def _calculate_avg_club_revenue(self, total_revenue: float, total_clubs: int) -> float:
        """Calculate average revenue per approved club"""
        if total_clubs > 0:
            return round(total_revenue / total_clubs, 2)
        return 0.0
    
    def _calculate_revenue_per_content(self, total_revenue: float, total_content: int) -> float:
        """Calculate revenue per content piece"""
        if total_content > 0:
            return round(total_revenue / total_content, 2)
        return 0.0
    
    async def get_recent_earnings(self, captain_id: str, filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get recent earnings data for captain with pagination and filters
        
        Args:
            captain_id: Captain's user ID
            filters: Dictionary containing filter parameters
            
        Returns:
            Dict with recent earnings data, pagination, and summary
        """
        try:
            logger.info(f"📊 Getting recent earnings for captain: {captain_id}")
            
            # Validate captain_id format
            if not ObjectId.is_valid(captain_id):
                logger.error(f"❌ Invalid captain_id format: {captain_id}")
                return {"success": False, "error": "Invalid captain ID format"}
            
            # Extract filter parameters
            page = filters.get("page", 1)
            limit = filters.get("limit", 20)
            club_id = filters.get("club_id")
            search = filters.get("search")
            membership_type = filters.get("membership_type")
            month = filters.get("month")
            year = filters.get("year")
            sort_by = filters.get("sort_by", "created_at")
            sort_order = filters.get("sort_order", "desc")
            
            # Build match criteria for clubs
            club_match = {
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}
            }
            
            if club_id:
                club_match["_id"] = ObjectId(club_id)
            
            # Get all clubs created by captain
            clubs = await self.club_collection.find(
                club_match,
                {
                    "_id": 1,
                    "name": 1,
                    "name_based_id": 1,
                    "members": 1,
                    "paid_members": 1
                }
            ).to_list(None)
            
            if not clubs:
                return {
                    "success": True,
                    "data": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total_items": 0,
                        "total_pages": 0,
                        "has_next": False,
                        "has_prev": False
                    },
                    "filters": filters,
                    "summary": {
                        "total_earnings": 0.0,
                        "total_members": 0,
                        "trial_members": 0,
                        "paid_members": 0
                    }
                }
            
            # Create club lookup for names
            club_lookup = {str(club["_id"]): {
                "name": club.get("name", "Unknown Club"),
                "name_based_id": club.get("name_based_id", "")
            } for club in clubs}
            
            # Collect all members from all clubs
            all_members = []
            
            logger.info(f"🔍 Found {len(clubs)} clubs for captain {captain_id}")
            
            for club in clubs:
                club_id_str = str(club["_id"])
                club_name = club.get("name", "Unknown Club")
                club_name_based_id = club.get("name_based_id", "")
                
                # Process trial members (from members array)
                for member in club.get("members", []):
                    if member.get("is_active", True) and member.get("membership_status") == "active":
                        # Get date fields - try multiple possible field names
                        created_at = member.get("created_at") or member.get("updated_at")
                        join_date = member.get("join_date") or member.get("created_at") or member.get("updated_at")
                        
                        member_data = {
                            "user_id": member.get("user_id", ""),
                            "full_name": member.get("full_name", "Unknown"),
                            "avatar_url": member.get("avatar_url"),
                            "club_id": club_id_str,
                            "club_name": club_name,
                            "club_name_based_id": club_name_based_id,
                            "membership_type": "trial",
                            "pricing_plan": member.get("pricing_plan", "trial"),
                            "membership_status": member.get("membership_status", "active"),
                            "status": "succeeded",
                            "payment_method": "stripe",
                            "amount_paid": 0.0,
                            "platform_fee": 0.0,
                            "your_share": 0.0,
                            "created_at": created_at,
                            "join_date": join_date
                        }
                        all_members.append(member_data)
                
                # Process paid members (from paid_members array)
                for member in club.get("paid_members", []):
                    if member.get("is_active", True) and member.get("membership_status") == "active":
                        amount_paid = member.get("amount_paid", 0.0)
                        your_share = amount_paid * 0.95  # 95% to captain
                        platform_fee = amount_paid * 0.05  # 5% to platform
                        
                        # Get date fields - try multiple possible field names
                        created_at = member.get("created_at") or member.get("updated_at")
                        join_date = member.get("join_date") or member.get("created_at") or member.get("updated_at")
                        
                        member_data = {
                            "user_id": member.get("user_id", ""),
                            "full_name": member.get("full_name", "Unknown"),
                            "avatar_url": member.get("avatar_url"),
                            "club_id": club_id_str,
                            "club_name": club_name,
                            "club_name_based_id": club_name_based_id,
                            "membership_type": "paid",
                            "pricing_plan": member.get("pricing_plan", "monthly"),
                            "membership_status": member.get("membership_status", "active"),
                            "status": "succeeded",
                            "payment_method": "stripe",
                            "amount_paid": amount_paid,
                            "platform_fee": platform_fee,
                            "your_share": your_share,
                            "created_at": created_at,
                            "join_date": join_date
                        }
                        all_members.append(member_data)
            
            # Apply filters
            filtered_members = self._apply_earnings_filters(all_members, filters)
            
            # Get user details for all members
            user_ids = list(set([member["user_id"] for member in filtered_members if member["user_id"]]))
            users = await self.user_collection.find(
                {"_id": {"$in": [ObjectId(uid) for uid in user_ids]}},
                {"_id": 1, "full_name": 1, "avatar_url": 1}
            ).to_list(None)
            
            user_lookup = {str(user["_id"]): {
                "full_name": user.get("full_name", "Unknown"),
                "avatar_url": user.get("avatar_url")
            } for user in users}
            
            # Update member data with user details
            for member in filtered_members:
                user_data = user_lookup.get(member["user_id"], {})
                member["full_name"] = user_data.get("full_name", member.get("full_name", "Unknown"))
                member["avatar_url"] = user_data.get("avatar_url", member.get("avatar_url"))
            
            # Sort members
            reverse = sort_order == "desc"
            
            try:
                if sort_by == "created_at":
                    # Handle None values properly for date sorting
                    filtered_members.sort(key=lambda x: x.get("created_at") if x.get("created_at") is not None else datetime.min, reverse=reverse)
                elif sort_by == "amount_paid":
                    filtered_members.sort(key=lambda x: x.get("amount_paid", 0), reverse=reverse)
                elif sort_by == "full_name":
                    filtered_members.sort(key=lambda x: x.get("full_name", ""), reverse=reverse)
                elif sort_by == "club_name":
                    filtered_members.sort(key=lambda x: x.get("club_name", ""), reverse=reverse)
                else:
                    # Default sort by created_at
                    filtered_members.sort(key=lambda x: x.get("created_at") if x.get("created_at") is not None else datetime.min, reverse=reverse)
            except Exception as e:
                logger.error(f"❌ Error sorting members: {e}")
                # If sorting fails, just return unsorted data
                pass
            
            # Apply pagination
            total_items = len(filtered_members)
            total_pages = (total_items + limit - 1) // limit
            start_index = (page - 1) * limit
            end_index = start_index + limit
            paginated_members = filtered_members[start_index:end_index]
            
            # Calculate summary
            total_earnings = sum(member["your_share"] for member in filtered_members)
            trial_members = len([m for m in filtered_members if m["membership_type"] == "trial"])
            paid_members = len([m for m in filtered_members if m["membership_type"] == "paid"])
            
            # Format dates
            for member in paginated_members:
                try:
                    if member.get("created_at"):
                        member["created_at"] = safe_datetime_serialize(member["created_at"])
                    else:
                        member["created_at"] = None
                    
                    if member.get("join_date"):
                        member["join_date"] = safe_datetime_serialize(member["join_date"])
                    else:
                        member["join_date"] = None
                except Exception as e:
                    logger.warning(f"⚠️ Error formatting dates for member {member.get('user_id', 'unknown')}: {e}")
                    # Set None values if date formatting fails
                    member["created_at"] = None
                    member["join_date"] = None
            
            return {
                "success": True,
                "data": paginated_members,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total_items": total_items,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1
                },
                "filters": filters,
                "summary": {
                    "total_earnings": round(total_earnings, 2),
                    "total_members": total_items,
                    "trial_members": trial_members,
                    "paid_members": paid_members
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting recent earnings: {e}")
            return {"success": False, "error": str(e)}
    
    def _apply_earnings_filters(self, members: List[Dict], filters: Dict[str, Any]) -> List[Dict]:
        """Apply filters to members list"""
        filtered = members
        
        # Search filter
        search = filters.get("search")
        if search:
            search_lower = search.lower()
            filtered = [
                m for m in filtered
                if (search_lower in m.get("full_name", "").lower() or 
                    search_lower in m.get("club_name", "").lower())
            ]
        
        # Membership type filter
        membership_type = filters.get("membership_type")
        if membership_type:
            filtered = [m for m in filtered if m.get("membership_type") == membership_type]
        
        # Month filter
        month = filters.get("month")
        year = filters.get("year")
        if month or year:
            filtered = [
                m for m in filtered
                if self._matches_date_filter(m.get("join_date"), month, year)
            ]
        
        return filtered
    
    def _matches_date_filter(self, date_value: Any, month: Optional[int], year: Optional[int]) -> bool:
        """Check if date matches month/year filter"""
        if not date_value:
            return False
        
        try:
            if isinstance(date_value, str):
                # Handle different date string formats
                if 'T' in date_value:
                    date_obj = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                else:
                    date_obj = datetime.fromisoformat(date_value)
            elif isinstance(date_value, datetime):
                date_obj = date_value
            else:
                return False
            
            if month and date_obj.month != month:
                return False
            if year and date_obj.year != year:
                return False
            
            return True
        except Exception as e:
            logger.warning(f"⚠️ Error parsing date {date_value}: {e}")
            return False
    
    async def get_captain_monthly_revenue(self, captain_id: str, months: int = 12) -> Dict[str, Any]:
        """
        Get captain's monthly revenue breakdown
        
        Args:
            captain_id: Captain's user ID
            months: Number of months to analyze (default: 12)
            
        Returns:
            Dict with monthly revenue data
        """
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=months * 30)
            
            logger.info(f"📈 Getting monthly revenue for captain {captain_id} for {months} months")
            
            # First try revenue_tracking collection
            revenue_pipeline = [
                {
                    "$match": {
                        "captain_id": ObjectId(captain_id),
                        "created_at": {"$gte": start_date, "$lte": end_date},
                        "status": "completed"
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "year": {"$year": "$created_at"},
                            "month": {"$month": "$created_at"}
                        },
                        "monthly_earnings": {"$sum": "$captain_amount"},
                        "monthly_platform_fees": {"$sum": "$platform_fee"},
                        "monthly_total_revenue": {"$sum": "$total_amount"},
                        "transaction_count": {"$sum": 1}
                    }
                },
                {
                    "$sort": {"_id.year": -1, "_id.month": -1}
                }
            ]
            
            result = await self.revenue_collection.aggregate(revenue_pipeline).to_list(None)
            
            # If no revenue_tracking data, try club_payments collection
            if not result or all(item["monthly_total_revenue"] == 0 for item in result):
                logger.info(f"🔍 No revenue_tracking data found, checking club_payments for monthly revenue")
                
                # Get all clubs created by this captain
                clubs = await self.club_collection.find({
                    "captain_id": captain_id,
                    "is_permanently_deleted": {"$ne": True}
                }, {"_id": 1}).to_list(None)
                
                if not clubs:
                    return {"success": True, "data": []}
                
                club_ids = [str(club["_id"]) for club in clubs]
                
                # Get monthly payments for captain's clubs
                payments_pipeline = [
                    {
                        "$match": {
                            "club_id": {"$in": club_ids},
                            "status": "succeeded",
                            "created_at": {"$gte": start_date, "$lte": end_date}
                        }
                    },
                    {
                        "$group": {
                            "_id": {
                                "year": {"$year": "$created_at"},
                                "month": {"$month": "$created_at"}
                            },
                            "monthly_total_revenue": {"$sum": "$amount"},
                            "transaction_count": {"$sum": 1}
                        }
                    },
                    {
                        "$sort": {"_id.year": -1, "_id.month": -1}
                    }
                ]
                
                payments_result = await self.payments_collection.aggregate(payments_pipeline).to_list(None)
                
                if payments_result:
                    # Convert payments result to revenue format
                    result = []
                    for item in payments_result:
                        total_revenue = item["monthly_total_revenue"]
                        captain_earnings = total_revenue * 0.95
                        platform_fees = total_revenue * 0.05
                        
                        result.append({
                            "_id": item["_id"],
                            "monthly_earnings": captain_earnings,
                            "monthly_platform_fees": platform_fees,
                            "monthly_total_revenue": total_revenue,
                            "transaction_count": item["transaction_count"]
                        })
            
            # Format monthly data
            monthly_data = []
            for item in result:
                month_name = datetime(item["_id"]["year"], item["_id"]["month"], 1).strftime("%B %Y")
                monthly_data.append({
                    "month": month_name,
                    "year": item["_id"]["year"],
                    "month_number": item["_id"]["month"],
                    "captain_earnings": item["monthly_earnings"],
                    "platform_fees": item["monthly_platform_fees"],
                    "total_revenue": item["monthly_total_revenue"],
                    "transaction_count": item["transaction_count"]
                })
            
            logger.info(f"✅ Monthly revenue data retrieved: {len(monthly_data)} months")
            return {"success": True, "data": monthly_data}
            
        except Exception as e:
            logger.error(f"❌ Error getting monthly revenue: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_captain_club_breakdown(self, captain_id: str) -> Dict[str, Any]:
        """
        Get detailed breakdown of captain's clubs with revenue and member data
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            Dict with club breakdown data
        """
        try:
            logger.info(f"🏢 Getting club breakdown for captain: {captain_id}")
            
            # Get all clubs created by this captain
            clubs = await self.club_collection.find({
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}
            }).to_list(None)
            
            club_breakdown = []
            
            for club in clubs:
                club_id = str(club["_id"])
                club_name = club.get("name", "Unknown Club")
                club_status = club.get("status", "unknown")
                
                # Get revenue for this specific club
                club_revenue = await self._get_club_revenue(club_id)
                
                # Get member count for this club
                member_count = await self._get_club_member_count(club_id)
                
                # Get content count for this club
                content_count = await self._get_club_content_count(club_id)
                
                club_breakdown.append({
                    "club_id": club_id,
                    "club_name": club_name,
                    "club_status": club_status,
                    "created_at": safe_datetime_serialize(club.get("created_at")),
                    "revenue": {
                        "total_earnings": club_revenue["captain_earnings"],
                        "platform_fees": club_revenue["platform_fees"],
                        "total_revenue": club_revenue["total_revenue"],
                        "transaction_count": club_revenue["transaction_count"]
                    },
                    "members": {
                        "total_members": member_count["total_members"],
                        "paid_members": member_count["paid_members"],
                        "trial_members": member_count["trial_members"]
                    },
                    "content": {
                        "total_content": content_count["total_content"],
                        "strategy_videos": content_count["strategy_videos"],
                        "training_videos": content_count["training_videos"],
                        "partner_links": content_count["partner_links"]
                    }
                })
            
            logger.info(f"✅ Club breakdown retrieved: {len(club_breakdown)} clubs")
            return {"success": True, "data": club_breakdown}
            
        except Exception as e:
            logger.error(f"❌ Error getting club breakdown: {e}")
            return {"success": False, "error": str(e)}
    
    async def _get_club_revenue(self, club_id: str) -> Dict[str, Any]:
        """Get revenue data for a specific club"""
        try:
            # First try revenue_tracking collection
            pipeline = [
                {
                    "$match": {
                        "club_id": ObjectId(club_id),
                        "status": "completed"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "captain_earnings": {"$sum": "$captain_amount"},
                        "platform_fees": {"$sum": "$platform_fee"},
                        "total_revenue": {"$sum": "$total_amount"},
                        "transaction_count": {"$sum": 1}
                    }
                }
            ]
            
            result = await self.revenue_collection.aggregate(pipeline).to_list(None)
            
            if result and result[0]["total_revenue"] > 0:
                return result[0]
            
            # If no revenue_tracking data, try club_payments collection
            payments_pipeline = [
                {
                    "$match": {
                        "club_id": club_id,
                        "status": "succeeded"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_revenue": {"$sum": "$amount"},
                        "transaction_count": {"$sum": 1}
                    }
                }
            ]
            
            payments_result = await self.payments_collection.aggregate(payments_pipeline).to_list(None)
            
            if payments_result and payments_result[0]["total_revenue"] > 0:
                total_revenue = payments_result[0]["total_revenue"]
                transaction_count = payments_result[0]["transaction_count"]
                
                # Calculate 95/5 split
                captain_earnings = total_revenue * 0.95
                platform_fees = total_revenue * 0.05
                
                return {
                    "captain_earnings": captain_earnings,
                    "platform_fees": platform_fees,
                    "total_revenue": total_revenue,
                    "transaction_count": transaction_count
                }
            else:
                return {
                    "captain_earnings": 0,
                    "platform_fees": 0,
                    "total_revenue": 0,
                    "transaction_count": 0
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting club revenue: {e}")
            return {
                "captain_earnings": 0,
                "platform_fees": 0,
                "total_revenue": 0,
                "transaction_count": 0
            }
    
    async def _get_club_member_count(self, club_id: str) -> Dict[str, Any]:
        """Get member count for a specific club"""
        try:
            # Get the club document with member arrays
            club = await self.club_collection.find_one(
                {"_id": ObjectId(club_id)},
                {"members": 1, "paid_members": 1}
            )
            
            if not club:
                return {
                    "total_members": 0,
                    "paid_members": 0,
                    "trial_members": 0
                }
            
            # Count paid members (from paid_members array)
            paid_members_list = club.get("paid_members", [])
            paid_members = 0
            for member in paid_members_list:
                if member.get("is_active", True) and member.get("membership_status") == "active":
                    paid_members += 1
            
            # Count trial members (from members array)
            members_list = club.get("members", [])
            trial_members = 0
            for member in members_list:
                if member.get("is_active", True) and member.get("membership_status") == "active":
                    trial_members += 1
            
            return {
                "total_members": paid_members + trial_members,
                "paid_members": paid_members,
                "trial_members": trial_members
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting club member count: {e}")
            return {
                "total_members": 0,
                "paid_members": 0,
                "trial_members": 0
            }
    
    async def _get_club_content_count(self, club_id: str) -> Dict[str, Any]:
        """Get content count for a specific club"""
        try:
            pipeline = [
                {
                    "$match": {
                        "club_id": ObjectId(club_id),
                        "is_active": True
                    }
                },
                {
                    "$group": {
                        "_id": "$section",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            result = await self.hub_collection.aggregate(pipeline).to_list(None)
            
            strategy_videos = 0
            training_videos = 0
            partner_links = 0
            
            for item in result:
                section = item["_id"]
                count = item["count"]
                
                if "strategy" in section.lower():
                    strategy_videos = count
                elif "training" in section.lower():
                    training_videos = count
                elif "partner" in section.lower():
                    partner_links = count
            
            return {
                "total_content": strategy_videos + training_videos + partner_links,
                "strategy_videos": strategy_videos,
                "training_videos": training_videos,
                "partner_links": partner_links
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting club content count: {e}")
            return {
                "total_content": 0,
                "strategy_videos": 0,
                "training_videos": 0,
                "partner_links": 0
            }

# Global instance
captain_revenue_service = CaptainRevenueService()

def get_captain_revenue_service():
    """Get captain revenue service instance"""
    return captain_revenue_service
