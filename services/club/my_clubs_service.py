from typing import Optional, List, Dict, Tuple
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from .db import get_club_collection, get_club_payments_collection, get_membership_collection, get_user_collection
from .models import MyClubsFilters, MyClubsSortOption, MyClubItem, MyClubsResponse, ClubStatus, PricingPlan
import logging

logger = logging.getLogger(__name__)

class MyClubsService:
    """Service for managing captain's clubs list with search, filtering, and pagination"""
    
    async def get_captain_clubs(
        self, 
        captain_id: str, 
        filters: Optional[MyClubsFilters] = None,
        sort_by: MyClubsSortOption = MyClubsSortOption.NEWEST,
        page: int = 1,
        page_size: int = 20
    ) -> Optional[MyClubsResponse]:
        """Get captain's clubs with search, filtering, and pagination"""
        try:
            club_collection = get_club_collection()
            payments_collection = get_club_payments_collection()
            membership_collection = get_membership_collection()
            
            # Build base query for captain's clubs
            # For captains: only show clubs with club_complete_step=5 when status is pending
            base_query = {
                "captain_id": captain_id,
                "is_permanently_deleted": {"$ne": True}  # Exclude permanently deleted clubs
            }
            
            # Add filtering logic for pending clubs
            # When captain logs in, only show clubs with club_complete_step=5 when status is pending
            # This ensures captains only see fully completed clubs that are pending approval
            pending_club_filter = {
                "$or": [
                    # Show clubs that are not pending (approved, rejected, inactive) - regardless of completion step
                    {"status": {"$ne": "pending"}},
                    # OR show pending clubs only if club_complete_step=5 (fully completed)
                    {
                        "status": "pending",
                        "club_complete_step": 5
                    }
                ]
            }
            base_query.update(pending_club_filter)
            
            logger.info(f"🔍 Searching for captain clubs with query: {base_query}")
            logger.info(f"🔍 Captain ID type: {type(captain_id)}, value: {captain_id}")
            logger.info(f"🔍 Applied pending club filter: {pending_club_filter}")
            
            # Apply filters
            if filters:
                logger.info(f"Applying filters: {filters}")
                if filters.search:
                    # Validate search term
                    search_term = filters.search.strip()
                    if len(search_term) >= 2:  # Minimum 2 characters for search
                        # Search by club name, description, or captain name
                        search_query = {
                            "$or": [
                                {"name": {"$regex": search_term, "$options": "i"}},
                                {"description": {"$regex": search_term, "$options": "i"}},
                                {"captain_details.full_name": {"$regex": search_term, "$options": "i"}}
                            ]
                        }
                        base_query.update(search_query)
                        logger.info(f"Added search query: {search_query}")
                    else:
                        logger.info(f"Search term too short, skipping search: '{search_term}'")
                
                if filters.status:
                    # Validate status filter
                    if filters.status in [ClubStatus.APPROVED, ClubStatus.PENDING, ClubStatus.REJECTED, ClubStatus.INACTIVE]:
                        base_query["status"] = filters.status
                        logger.info(f"Added status filter: {filters.status}")
                    else:
                        logger.warning(f"Invalid status filter value: {filters.status}, skipping status filter")
                
                if filters.pricing_plan:
                    # Use $elemMatch to properly filter pricing plans
                    base_query["pricing_plans"] = {
                        "$elemMatch": {
                            "$or": [
                                {"frequency": filters.pricing_plan},
                                {"plan": filters.pricing_plan}
                            ]
                        }
                    }
            
            logger.info(f"Final base query: {base_query}")
            
            # Get total count for pagination
            logger.info(f"Executing count query: {base_query}")
            start_time = datetime.now(timezone.utc)
            total_count = await club_collection.count_documents(base_query)
            count_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(f"Count query completed in {count_time:.3f}s, found {total_count} clubs")
            
            if total_count == 0:
                return MyClubsResponse(
                    clubs=[],
                    total_count=0,
                    total_members=0,
                    total_moderators=0,
                    page=page,
                    page_size=page_size,
                    total_pages=0,
                    has_next=False,
                    has_previous=False
                )
            
            # Calculate pagination
            total_pages = (total_count + page_size - 1) // page_size
            skip = (page - 1) * page_size
            
            # Build sort criteria
            sort_criteria = []
            if sort_by == MyClubsSortOption.MOST_MEMBERS:
                # For most members sorting, we'll sort by created_at first, then sort by actual member count after processing
                sort_criteria = [("created_at", -1)]
            elif sort_by == MyClubsSortOption.NEWEST:
                sort_criteria = [("created_at", -1)]
            elif sort_by == MyClubsSortOption.OLDEST:
                sort_criteria = [("created_at", 1)]
            else:
                sort_criteria = [("created_at", -1)]  # Default to newest
            
            # Get clubs with pagination and sorting
            logger.info(f"Base query: {base_query}")
            logger.info(f"Sort criteria: {sort_criteria}")
            logger.info(f"Pagination: skip={skip}, limit={page_size}")
            
            start_time = datetime.now(timezone.utc)
            clubs_cursor = club_collection.find(base_query).sort(sort_criteria).skip(skip).limit(page_size)
            clubs = await clubs_cursor.to_list(length=page_size)
            query_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(f"Main query completed in {query_time:.3f}s, found {len(clubs)} clubs")
            
            # Process each club to get additional data
            club_items = []
            for club in clubs:
                club_item = await self._process_club_item(club, payments_collection, membership_collection, None, calculate_total_revenue=True, user_id=captain_id)
                if club_item:
                    club_items.append(club_item)
            
            # Apply post-processing sorting for most_members option
            if sort_by == MyClubsSortOption.MOST_MEMBERS:
                logger.info("Applying post-processing sort by most members")
                club_items.sort(key=lambda x: x.total_members, reverse=True)
                logger.info(f"Sorted clubs by member count: {[(c.club_name, c.total_members) for c in club_items]}")
            
            # Calculate pagination flags
            has_next = page < total_pages
            has_previous = page > 1
            
            # Calculate totals
            total_members = sum(club.total_members for club in club_items)
            total_moderators = sum(club.moderator_count for club in club_items)
            
            return MyClubsResponse(
                clubs=club_items,
                total_count=total_count,
                total_members=total_members,
                total_moderators=total_moderators,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous
            )
            
        except Exception as e:
            logger.error(f"Error getting captain clubs: {e}")
            return None
    
    async def _process_club_item(
        self, 
        club: Dict, 
        payments_collection, 
        membership_collection,
        member_status_info: Optional[Dict] = None,
        calculate_total_revenue: bool = False,
        user_id: Optional[str] = None
    ) -> Optional[MyClubItem]:
        """Process a club document into MyClubItem with additional data"""
        try:
            club_id = str(club["_id"])
            club_name_based_id = club.get("name_based_id", "")
            
            # Debug: Log all available fields in the club document
            logger.info(f"Club document fields for {club_id}: {list(club.keys())}")
            logger.info(f"Full club document for {club_id}: {club}")
            
            # Get pricing information (priority: monthly > yearly > quarterly)
            raw_pricing_plans = club.get("pricing_plans", [])
            logger.info(f"Raw pricing plans for club {club_id}: {raw_pricing_plans}")
            
            pricing = self._get_priority_pricing(raw_pricing_plans)
            logger.info(f"Priority pricing for club {club_id}: {pricing}")
            
            # Get full pricing plans
            pricing_plans = raw_pricing_plans
            
            # Get total members count
            total_members = await self._get_club_member_count(club_id, membership_collection)
            
            # Get monthly revenue
            monthly_revenue = await self._get_club_monthly_revenue(club_id, payments_collection)
            
            # Calculate total revenue if requested (for captains)
            total_revenue = None
            if calculate_total_revenue:
                total_revenue = await self._calculate_club_total_revenue(club_id)
            
            # Calculate combined member status if member status info is provided
            member_combined_status = None
            if member_status_info:
                member_status = member_status_info.get("status")
                membership_status = member_status_info.get("membership_status")
                
                # Combined status logic: active only if both are active, inactive otherwise
                if member_status == "active" and membership_status == "active":
                    member_combined_status = "active"
                else:
                    member_combined_status = "inactive"
            
            # Get is_chat_open and push_type for this club
            is_chat_open = False
            push_type = ""
            
            if user_id and club_name_based_id:
                try:
                    from bson import ObjectId
                    from core.database.collections import get_collections
                    
                    collections = get_collections()
                    users_col = collections.get_users_collection()
                    notifications_col = collections.get_notifications_collection()
                    
                    # Get user's chat_open_clubs data
                    user = await users_col.find_one(
                        {"_id": ObjectId(user_id)},
                        {"chat_open_clubs": 1}
                    )
                    
                    if user and "chat_open_clubs" in user:
                        # Find this club's entry
                        for club_entry in user["chat_open_clubs"]:
                            if club_entry.get("club_id") == club_name_based_id:
                                is_chat_open = club_entry.get("is_chat_open", False)
                                break
                    
                    # Get latest notification for this club to extract push_type
                    latest_notification = await notifications_col.find_one(
                        {
                            "user_id": user_id,
                            "data.club_id": club_name_based_id
                        },
                        sort=[("created_at", -1)]
                    )
                    
                    if latest_notification:
                        push_type = latest_notification.get("push_type", "")
                    
                except Exception as chat_error:
                    logger.warning(f"Error getting chat status for club {club_id}: {chat_error}")
                    # Continue with defaults if error occurs
            
            # Create MyClubItem
            # Ensure revenue fields are never None (default to 0.0 for Pydantic validation)
            revenue_value = total_revenue if total_revenue is not None else 0.0
            
            club_item = MyClubItem(
                club_id=club_id,
                club_name=club.get("name", ""),
                name_based_id=club.get("name_based_id", ""),
                created_at=club.get("created_at", datetime.now(timezone.utc)),
                status=club.get("status", ClubStatus.PENDING),
                pricing=pricing,
                pricing_plans=pricing_plans,
                total_members=total_members,
                moderator_count=club.get("moderator_count", 0),
                monthly_revenue=revenue_value,
                total_revenue=revenue_value,
                logo_url=club.get("logo_url"),
                # Add member status information if provided
                member_status=member_status_info.get("status") if member_status_info else None,
                membership_status=member_status_info.get("membership_status") if member_status_info else None,
                member_combined_status=member_combined_status,
                # Add club deletion/reactivation fields
                is_permanently_deleted=club.get("is_permanently_deleted", False),
                is_temporarily_deleted=club.get("is_temporarily_deleted", False),
                reactivated_at=club.get("reactivated_at"),
                reactivated_by=club.get("reactivated_by"),
                deletion_reason=club.get("deletion_reason"),
                deleted_at=club.get("deleted_at"),
                deleted_by=club.get("deleted_by"),
                # Add chat status fields
                is_chat_open=is_chat_open,
                push_type=push_type
            )
            
            return club_item
            
        except Exception as e:
            logger.error(f"Error processing club item: {e}")
            return None
    
    def _get_priority_pricing(self, pricing_plans: List[Dict]) -> Optional[Dict]:
        """Get priority pricing plan (daily > monthly > yearly > quarterly) with full details"""
        if not pricing_plans:
            logger.info("No pricing plans found")
            return None
        
        logger.info(f"Processing pricing plans: {pricing_plans}")
        
        # Sort by priority: daily (1), monthly (2), yearly (3), quarterly (4)
        priority_map = {
            "daily": 1,
            "monthly": 2,
            "yearly": 3,
            "quarterly": 4
        }
        
        # Find the plan with highest priority (lowest number)
        highest_priority_plan = None
        highest_priority = float('inf')
        
        for i, plan in enumerate(pricing_plans):
            logger.info(f"Processing plan {i}: {plan}")
            # Check both 'plan' and 'frequency' fields for compatibility
            plan_type = plan.get("plan") or plan.get("frequency")
            logger.info(f"Plan type extracted: {plan_type}")
            
            if plan_type and plan_type.lower() in priority_map:
                priority = priority_map[plan_type.lower()]
                logger.info(f"Priority for {plan_type}: {priority}")
                if priority < highest_priority:
                    highest_priority = priority
                    highest_priority_plan = plan
                    logger.info(f"New highest priority plan: {plan}")
            else:
                logger.info(f"Plan type {plan_type} not found in priority map")
        
        logger.info(f"Final highest priority plan: {highest_priority_plan}")
        return highest_priority_plan
    
    async def _get_club_member_count(self, club_id: str, membership_collection) -> int:
        """Get total member count for a club"""
        try:
            # First try to get the count from the club document itself
            club_collection = get_club_collection()
            club = await club_collection.find_one({"_id": ObjectId(club_id)})
            
            if club:
                # Use total_members if available, otherwise sum member_count + paid_member_count
                if "total_members" in club:
                    member_count = club.get("total_members", 0)
                    logger.info(f"Using total_members from club document: {member_count}")
                else:
                    member_count = club.get("member_count", 0) + club.get("paid_member_count", 0)
                    logger.info(f"Calculated member count from club document: member_count={club.get('member_count', 0)} + paid_member_count={club.get('paid_member_count', 0)} = {member_count}")
                
                return member_count
            else:
                # Fallback: Count active memberships for this club
                logger.warning(f"Club {club_id} not found, falling back to membership collection count")
                member_count = await membership_collection.count_documents({
                    "club_id": club_id,
                    "subscription_status": {"$in": ["active", "trial", "paid", "subscribed"]}
                })
                return member_count
                
        except Exception as e:
            logger.error(f"Error getting club member count: {e}")
            return 0
    
    async def _get_club_monthly_revenue(self, club_id: str, payments_collection) -> float:
        """Get monthly revenue for a club"""
        try:
            # Calculate date range for current month
            now = datetime.now(timezone.utc)
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Get payments for current month
            monthly_payments = await payments_collection.find({
                "club_id": club_id,
                "status": "succeeded",
                "created_at": {"$gte": start_of_month}
            }).to_list(length=None)
            
            # Calculate total monthly revenue
            monthly_revenue = sum(payment.get("amount", 0.0) for payment in monthly_payments)
            
            return round(monthly_revenue, 2)
            
        except Exception as e:
            logger.error(f"Error getting club monthly revenue: {e}")
            return 0.0
    
    async def _calculate_club_total_revenue(self, club_id: str) -> float:
        """
        Calculate club-specific total revenue from paid_members array
        
        Args:
            club_id: Club ID (ObjectId string)
            
        Returns:
            float: Total revenue for this specific club (captain's 95% share)
        """
        try:
            # Get club document with paid_members array
            club_collection = get_club_collection()
            club_doc = await club_collection.find_one({"_id": ObjectId(club_id)})
            
            if not club_doc:
                logger.warning(f"Club {club_id} not found")
                return 0.0
            
            club_name_based_id = club_doc.get("name_based_id", "")
            paid_members = club_doc.get("paid_members", [])
            
            logger.info(f"Calculating total revenue for club {club_name_based_id} with {len(paid_members)} paid members")
            
            # Calculate total revenue from paid_members
            total_amount_paid = 0.0
            
            for member in paid_members:
                amount_paid = member.get("amount_paid", 0.0)
                if amount_paid > 0:
                    total_amount_paid += amount_paid
            
            # Calculate captain's share (95%)
            captain_share = total_amount_paid * 0.95
            
            logger.info(f"Club {club_name_based_id} - Total paid: ${total_amount_paid}, Captain's share (95%): ${captain_share}")
            
            return round(captain_share, 2)
                
        except Exception as e:
            logger.error(f"Error calculating club total revenue: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return 0.0
    #git added
    async def get_member_joined_clubs(
        self, 
        member_id: str, 
        filters: Optional[MyClubsFilters] = None,
        sort_by: MyClubsSortOption = MyClubsSortOption.NEWEST,
        page: int = 1,
        page_size: int = 20
    ) -> Optional[MyClubsResponse]:
        """Get member's joined clubs with search, filtering, and pagination"""
        try:
            club_collection = get_club_collection()
            payments_collection = get_club_payments_collection()
            membership_collection = get_membership_collection()
            user_collection = get_user_collection()
            
            # First, try to get clubs from the clubs_joined array in users collection
            logger.info(f"🔍 DEBUG: Looking up user with member_id: {member_id}")
            user = await user_collection.find_one({"_id": ObjectId(member_id)})
            logger.info(f"🔍 DEBUG: User found: {user is not None}")
            if user:
                logger.info(f"🔍 DEBUG: User has 'clubs_joined' key: {'clubs_joined' in user}")
                logger.info(f"🔍 DEBUG: User clubs_joined value: {user.get('clubs_joined', 'NOT FOUND')}")
            
            club_ids = []
            member_club_status = {}  # Store member's status for each club
            
            if user and user.get("clubs_joined"):
                clubs_joined = user["clubs_joined"]
                logger.info(f"✅ Found {len(clubs_joined)} clubs in user's clubs_joined array")
                
                # Get club IDs from clubs_joined array (all memberships - active and inactive)
                for club_data in clubs_joined:
                    try:
                        club_id = club_data.get("club_id", "")
                        logger.info(f"🔍 DEBUG: Processing club_id: {club_id} (type: {type(club_id)})")
                        club_ids.append(ObjectId(club_id))
                        
                        # Store member's status for this club
                        member_club_status[club_id] = {
                            "status": club_data.get("status", "active"),
                            "membership_status": club_data.get("membership_status", "active")
                        }
                    except Exception as e:
                        logger.warning(f"⚠️ Error processing club_id {club_data.get('club_id')}: {e}")
                        continue
            else:
                # Fallback: Get all memberships for this member (all statuses)
                logger.info(f"⚠️ No clubs_joined array found for user {member_id}, checking membership collection")
                memberships = await membership_collection.find({
                    "user_id": member_id
                }).to_list(None)
                
                logger.info(f"📊 Found {len(memberships)} memberships in membership collection")
                
                # Log some membership details for debugging
                for i, membership in enumerate(memberships[:3]):  # Log first 3 memberships
                    logger.info(f"🔍 DEBUG: Membership {i+1}: club_id={membership.get('club_id')}, status={membership.get('subscription_status')}, user_id={membership.get('user_id')}")
                
                # Get club IDs from memberships
                for membership in memberships:
                    try:
                        club_id = membership["club_id"]
                        logger.info(f"🔍 DEBUG: Processing membership club_id: {club_id} (type: {type(club_id)})")
                        club_ids.append(ObjectId(club_id))
                        
                        # Store member's status for this club (from membership collection)
                        subscription_status = membership.get("subscription_status", "active")
                        member_club_status[club_id] = {
                            "status": "active" if subscription_status in ["active", "pending", "trial"] else "inactive",
                            "membership_status": "active" if subscription_status in ["active", "pending", "trial"] else "inactive"
                        }
                    except Exception as e:
                        logger.warning(f"⚠️ Error processing membership club_id {membership.get('club_id')}: {e}")
                        continue
            
            logger.info(f"📊 Total club_ids collected: {len(club_ids)}")
            if club_ids:
                logger.info(f"🔍 DEBUG: Club IDs to query: {[str(cid) for cid in club_ids]}")
            
            if not club_ids:
                logger.warning(f"❌ No active memberships found for member {member_id}")
                return MyClubsResponse(
                    clubs=[],
                    total_count=0,
                    total_members=0,
                    total_moderators=0,
                    page=page,
                    page_size=page_size,
                    total_pages=0,
                    has_next=False,
                    has_previous=False
                )
            
            # Build base query for member's joined clubs
            base_query = {"_id": {"$in": club_ids}}
            logger.info(f"🔍 DEBUG: Base query for clubs: {base_query}")
            
            # Apply filters
            if filters:
                logger.info(f"Applying filters to member's clubs: {filters}")
                if filters.search:
                    # Validate search term
                    search_term = filters.search.strip()
                    if len(search_term) >= 2:  # Minimum 2 characters for search
                        # Search by club name, description, or captain name
                        search_query = {
                            "$or": [
                                {"name": {"$regex": search_term, "$options": "i"}},
                                {"description": {"$regex": search_term, "$options": "i"}},
                                {"captain_details.full_name": {"$regex": search_term, "$options": "i"}}
                            ]
                        }
                        base_query = {"$and": [base_query, search_query]}
                
                if filters.status:
                    base_query["status"] = filters.status.value
                
                # Note: member_status filtering is handled after processing clubs
                # since it requires checking the member's status in each club
            
            # Get total count for pagination (before member_status filtering)
            total_count = await club_collection.count_documents(base_query)
            logger.info(f"📊 DEBUG: Total clubs found matching query: {total_count}")
            
            # Calculate pagination
            skip = (page - 1) * page_size
            total_pages = (total_count + page_size - 1) // page_size
            
            # Build sort criteria
            sort_criteria = []
            if sort_by == MyClubsSortOption.MOST_MEMBERS:
                # For most members sorting, we'll sort by created_at first, then sort by actual member count after processing
                sort_criteria = [("created_at", -1)]
            elif sort_by == MyClubsSortOption.NEWEST:
                sort_criteria = [("created_at", -1)]
            elif sort_by == MyClubsSortOption.OLDEST:
                sort_criteria = [("created_at", 1)]
            else:
                sort_criteria = [("created_at", -1)]  # Default to newest
            
            # Get clubs with pagination
            clubs_cursor = club_collection.find(base_query).sort(sort_criteria).skip(skip).limit(page_size)
            clubs = await clubs_cursor.to_list(length=None)
            logger.info(f"📊 DEBUG: Clubs retrieved after pagination: {len(clubs)}")
            if clubs:
                logger.info(f"🔍 DEBUG: First club: name={clubs[0].get('name')}, id={clubs[0].get('_id')}, status={clubs[0].get('status')}")
            
            # Process clubs
            processed_clubs = []
            for club in clubs:
                club_id = str(club["_id"])
                member_status_info = member_club_status.get(club_id)
                club_item = await self._process_club_item(club, payments_collection, membership_collection, member_status_info, user_id=member_id)
                if club_item:
                    processed_clubs.append(club_item)
            
            # Apply member_status filtering if specified
            if filters and filters.member_status:
                logger.info(f"Filtering clubs by member_status: {filters.member_status}")
                filtered_clubs = []
                for club in processed_clubs:
                    if club.member_combined_status == filters.member_status:
                        filtered_clubs.append(club)
                processed_clubs = filtered_clubs
                # Update total_count after filtering
                total_count = len(processed_clubs)
                total_pages = (total_count + page_size - 1) // page_size
                logger.info(f"Filtered to {len(processed_clubs)} clubs with member_status: {filters.member_status}")
            
            # Apply post-processing sorting for most_members option
            if sort_by == MyClubsSortOption.MOST_MEMBERS:
                logger.info("Applying post-processing sort by most members")
                processed_clubs.sort(key=lambda x: x.total_members, reverse=True)
                logger.info(f"Sorted clubs by member count: {[(c.club_name, c.total_members) for c in processed_clubs]}")
            
            # Calculate pagination flags
            has_next = page < total_pages
            has_previous = page > 1
            
            logger.info(f"Retrieved {len(processed_clubs)} joined clubs for member {member_id}")
            
            # Calculate totals
            total_members = sum(club.total_members for club in processed_clubs)
            total_moderators = sum(club.moderator_count for club in processed_clubs)
            
            return MyClubsResponse(
                clubs=processed_clubs,
                total_count=total_count,
                total_members=total_members,
                total_moderators=total_moderators,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous
            )
            
        except Exception as e:
            logger.error(f"Error getting member's joined clubs: {e}")
            return None

    async def get_user_accessible_clubs(
        self,
        user_id: str,
        user_role: str,
        filters: Optional[MyClubsFilters] = None,
        sort_by: MyClubsSortOption = MyClubsSortOption.NEWEST,
        page: int = 1,
        page_size: int = 20
    ) -> Optional[MyClubsResponse]:
        """
        Get all accessible clubs for a user regardless of their current role.
        OPTIMIZED VERSION: Uses parallel queries instead of sequential queries.
        
        For any user, this method will:
        1. Get clubs they created (if they're a captain)
        2. Get clubs they joined as members
        3. Get clubs they're assigned to as moderators
        4. Combine and deduplicate the results
        """
        try:
            import time
            import asyncio
            service_start_time = time.time()
            logger.info(f"🔍 Getting all accessible clubs for user {user_id} with role {user_role} (OPTIMIZED)")
            
            all_clubs = []
            processed_club_ids = set()
            
            # OPTIMIZATION: Execute all queries in parallel instead of sequentially
            parallel_start = time.time()
            tasks = []
            
            # 1. Get clubs created by the user (if they're a captain)
            if user_role.lower() == "captain":
                logger.info(f"Getting created clubs for captain {user_id}")
                captain_task = self.get_captain_clubs(
                    captain_id=user_id,
                    filters=filters,
                    sort_by=sort_by,
                    page=1,  # Get all clubs, we'll paginate later
                    page_size=1000  # Large number to get all clubs
                )
                tasks.append(("captain", captain_task))
            
            # 2. Get clubs joined as a member
            logger.info(f"Getting joined clubs for user {user_id}")
            member_task = self.get_member_joined_clubs(
                member_id=user_id,
                filters=filters,
                sort_by=sort_by,
                page=1,  # Get all clubs, we'll paginate later
                page_size=1000  # Large number to get all clubs
            )
            tasks.append(("member", member_task))
            
            # 3. Get clubs where user is assigned as moderator (from detailed_moderators array)
            logger.info(f"Getting moderator clubs for user {user_id}")
            moderator_task = self._get_user_moderator_clubs(
                user_id=user_id,
                filters=filters,
                sort_by=sort_by,
                page=1,  # Get all clubs, we'll paginate later
                page_size=1000  # Large number to get all clubs
            )
            tasks.append(("moderator", moderator_task))
            
            # Execute all queries in parallel
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)
            parallel_time = time.time() - parallel_start
            logger.info(f"⏱️ OPTIMIZED: Parallel queries took {parallel_time:.3f}s")
            
            # Process results - map results back to their task names
            # IMPORTANT: Cannot use fixed indices because captain task is conditional!
            # For Members: tasks = [("member", ...), ("moderator", ...)]
            # For Captains: tasks = [("captain", ...), ("member", ...), ("moderator", ...)]
            result_map = {}
            for i, (task_name, _) in enumerate(tasks):
                if i < len(results) and not isinstance(results[i], Exception):
                    result_map[task_name] = results[i]
                else:
                    result_map[task_name] = None
                    if i < len(results) and isinstance(results[i], Exception):
                        logger.error(f"❌ Error in {task_name} task: {results[i]}")
            
            logger.info(f"🔍 DEBUG: Result map keys: {list(result_map.keys())}")
            
            # Extract results from the map
            captain_result = result_map.get("captain")
            member_result = result_map.get("member")
            moderator_clubs = result_map.get("moderator")
            
            # Process captain clubs
            if captain_result and captain_result.clubs:
                for club in captain_result.clubs:
                    club_id = club.club_id
                    if club_id not in processed_club_ids:
                        all_clubs.append(club)
                        processed_club_ids.add(club_id)
                logger.info(f"Found {len(captain_result.clubs)} created clubs")
            
            # Process member clubs
            if member_result and member_result.clubs:
                for club in member_result.clubs:
                    club_id = club.club_id
                    if club_id not in processed_club_ids:
                        all_clubs.append(club)
                        processed_club_ids.add(club_id)
                logger.info(f"Found {len(member_result.clubs)} joined clubs")
            
            # Process moderator clubs
            if moderator_clubs and moderator_clubs.clubs:
                for club in moderator_clubs.clubs:
                    club_id = club.club_id
                    if club_id not in processed_club_ids:
                        all_clubs.append(club)
                        processed_club_ids.add(club_id)
                logger.info(f"Found {len(moderator_clubs.clubs)} moderator clubs")
            
            # 4. Apply additional filtering if needed
            if filters and filters.member_status:
                logger.info(f"Applying member_status filter: {filters.member_status}")
                filtered_clubs = []
                for club in all_clubs:
                    # Check if the user's status in this club matches the filter
                    if hasattr(club, 'member_combined_status'):
                        if club.member_combined_status == filters.member_status:
                            filtered_clubs.append(club)
                    elif hasattr(club, 'member_status'):
                        if club.member_status == filters.member_status:
                            filtered_clubs.append(club)
                    else:
                        # If no member status info, include the club
                        filtered_clubs.append(club)
                all_clubs = filtered_clubs
            
            # 5. Sort clubs
            if sort_by == MyClubsSortOption.MOST_MEMBERS:
                all_clubs.sort(key=lambda x: getattr(x, 'total_members', 0), reverse=True)
            elif sort_by == MyClubsSortOption.NEWEST:
                all_clubs.sort(key=lambda x: getattr(x, 'created_at', datetime.min), reverse=True)
            elif sort_by == MyClubsSortOption.OLDEST:
                all_clubs.sort(key=lambda x: getattr(x, 'created_at', datetime.max))
            
            # 6. Apply pagination
            total_count = len(all_clubs)
            total_pages = (total_count + page_size - 1) // page_size
            has_next = page < total_pages
            has_previous = page > 1
            
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_clubs = all_clubs[start_index:end_index]
            
            logger.info(f"Returning {len(paginated_clubs)} clubs out of {total_count} total accessible clubs for user {user_id}")
            
            # Add user role information to each club - OPTIMIZED BATCH PROCESSING
            role_start = time.time()
            club_user_roles = await self._determine_user_roles_batch(user_id, [club.club_id for club in paginated_clubs])
            for club in paginated_clubs:
                club.user_role = club_user_roles.get(club.club_id, "Member")
            role_time = time.time() - role_start
            logger.info(f"⏱️ OPTIMIZED: Batch role determination took {role_time:.3f}s for {len(paginated_clubs)} clubs")
            
            # Calculate totals
            total_members = sum(club.total_members for club in paginated_clubs)
            total_moderators = sum(club.moderator_count for club in paginated_clubs)
            
            total_service_time = time.time() - service_start_time
            logger.info(f"✅ OPTIMIZED: Total service time took {total_service_time:.3f}s - Final result: {len(paginated_clubs)} clubs")
            
            return MyClubsResponse(
                clubs=paginated_clubs,
                total_count=total_count,
                total_members=total_members,
                total_moderators=total_moderators,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous
            )
            
        except Exception as e:
            logger.error(f"Error getting user accessible clubs: {e}")
            return None
    
    async def _determine_user_roles_batch(self, user_id: str, club_ids: List[str]) -> Dict[str, str]:
        """
        OPTIMIZED: Determine user's role in multiple clubs using a single aggregation query
        This eliminates the N+1 query problem by fetching all club roles in one database call.
        
        Args:
            user_id: User ID
            club_ids: List of club IDs to check
            
        Returns:
            Dict mapping club_id to user role ("Captain", "Moderator", "Member", "None")
        """
        try:
            if not club_ids:
                return {}
            
            club_collection = get_club_collection()
            
            # Convert string IDs to ObjectIds
            object_ids = []
            for club_id in club_ids:
                try:
                    object_ids.append(ObjectId(club_id))
                except Exception:
                    logger.warning(f"Invalid club_id format: {club_id}")
                    continue
            
            if not object_ids:
                return {}
            
            # Single aggregation query to get all club roles at once
            pipeline = [
                {"$match": {"_id": {"$in": object_ids}}},
                {
                    "$project": {
                        "_id": 1,
                        "captain_id": 1,
                        "moderators": 1,
                        "detailed_moderators": 1,
                        "members": 1,
                        "paid_members": 1,
                        "user_role": {
                            "$cond": {
                                "if": {"$eq": ["$captain_id", user_id]},
                                "then": "Captain",
                                "else": {
                                    "$cond": {
                                        "if": {
                                            "$or": [
                                                {"$in": [user_id, "$moderators.user_id"]},
                                                {"$in": [user_id, "$detailed_moderators.user_id"]}
                                            ]
                                        },
                                        "then": "Moderator",
                                        "else": {
                                            "$cond": {
                                                "if": {
                                                    "$or": [
                                                        {"$in": [user_id, "$members.user_id"]},
                                                        {"$in": [user_id, "$paid_members.user_id"]}
                                                    ]
                                                },
                                                "then": "Member",
                                                "else": "None"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            ]
            
            results = await club_collection.aggregate(pipeline).to_list(length=None)
            
            # Convert results to dictionary
            club_roles = {}
            for result in results:
                club_id = str(result["_id"])
                role = result.get("user_role", "None")
                club_roles[club_id] = role
            
            logger.info(f"🔍 Batch role determination: Found roles for {len(club_roles)} clubs")
            return club_roles
            
        except Exception as e:
            logger.error(f"Error in batch role determination: {e}")
            # Fallback to individual role determination
            club_roles = {}
            for club_id in club_ids:
                try:
                    role = await self._determine_user_role_in_club(user_id, club_id)
                    club_roles[club_id] = role
                except Exception as e2:
                    logger.error(f"Error determining role for club {club_id}: {e2}")
                    club_roles[club_id] = "None"
            return club_roles
    
    async def _determine_user_role_in_club(self, user_id: str, club_id: str) -> str:
        """
        Determine the user's role in a specific club
        
        Returns:
            str: "Captain", "Moderator", or "Member"
        """
        try:
            club_collection = get_club_collection()
            
            # Get the club document
            try:
                club_object_id = ObjectId(club_id)
                club = await club_collection.find_one({"_id": club_object_id})
            except Exception as e:
                logger.error(f"Invalid club_id format: {club_id}, error: {e}")
                return "None"
                
            if not club:
                logger.warning(f"Club {club_id} not found when determining user role for {user_id}")
                return "None"  # Return None instead of Member to indicate no access
            
            # 1. Check if user is the captain
            captain_id = str(club.get("captain_id"))
            if captain_id == user_id:
                logger.info(f"User {user_id} is captain of club {club_id}")
                return "Captain"
            
            # 2. Check if user is a moderator (in detailed_moderators array)
            moderators = club.get("detailed_moderators", [])
            for moderator in moderators:
                if moderator.get("user_id") == user_id:
                    logger.info(f"User {user_id} is moderator of club {club_id}")
                    return "Moderator"
            
            # 3. Check if user is a member (in members or paid_members array)
            members = club.get("members", [])
            paid_members = club.get("paid_members", [])
            
            logger.info(f"Checking membership for user {user_id} in club {club_id}")
            logger.info(f"Club has {len(members)} trial members and {len(paid_members)} paid members")
            logger.info(f"Trial member IDs: {[m.get('user_id') for m in members]}")
            logger.info(f"Paid member IDs: {[m.get('user_id') for m in paid_members]}")
            
            for member in members:
                if member.get("user_id") == user_id:
                    logger.info(f"User {user_id} found as trial member in club {club_id}")
                    return "Member"
            
            for member in paid_members:
                if member.get("user_id") == user_id:
                    logger.info(f"User {user_id} found as paid member in club {club_id}")
                    return "Member"
            
            # If not found in any role, return "None" to indicate no access
            logger.warning(f"User {user_id} not found in any role for club {club_id}")
            return "None"
            
        except Exception as e:
            logger.error(f"Error determining user role in club {club_id}: {e}")
            return "None"  # Return None instead of Member to indicate no access
    
    async def _get_user_moderator_clubs(
        self,
        user_id: str,
        filters: Optional[MyClubsFilters] = None,
        sort_by: MyClubsSortOption = MyClubsSortOption.NEWEST,
        page: int = 1,
        page_size: int = 20,
    ) -> Optional[MyClubsResponse]:
        """Get clubs where user is assigned as moderator (from detailed_moderators array)"""
        try:
            club_collection = get_club_collection()
            payments_collection = get_club_payments_collection()
            membership_collection = get_membership_collection()

            # Find clubs where the user is in detailed_moderators array
            base_query = {
                "detailed_moderators.user_id": user_id,
                "is_permanently_deleted": {"$ne": True}  # Exclude permanently deleted clubs
            }

            # Apply filters
            if filters:
                logger.info(f"Applying filters to moderator's clubs: {filters}")
                if filters.search:
                    # Validate search term
                    search_term = filters.search.strip()
                    if len(search_term) >= 2:  # Minimum 2 characters for search
                        # Search by club name, description, or captain name
                        search_query = {
                            "$or": [
                                {"name": {"$regex": search_term, "$options": "i"}},
                                {"description": {"$regex": search_term, "$options": "i"}},
                                {"captain_details.full_name": {"$regex": search_term, "$options": "i"}}
                            ]
                        }
                        base_query = {"$and": [base_query, search_query]}

                if filters.status:
                    base_query["status"] = filters.status.value

            # Get total count for pagination
            total_count = await club_collection.count_documents(base_query)

            if total_count == 0:
                return MyClubsResponse(
                    clubs=[],
                    total_count=0,
                    total_members=0,
                    total_moderators=0,
                    page=page,
                    page_size=page_size,
                    total_pages=0,
                    has_next=False,
                    has_previous=False
                )

            # Calculate pagination
            skip = (page - 1) * page_size
            total_pages = (total_count + page_size - 1) // page_size

            # Build sort criteria
            sort_criteria = []
            if sort_by == MyClubsSortOption.MOST_MEMBERS:
                # For most members sorting, we'll sort by created_at first, then sort by actual member count after processing
                sort_criteria = [("created_at", -1)]
            elif sort_by == MyClubsSortOption.NEWEST:
                sort_criteria = [("created_at", -1)]
            elif sort_by == MyClubsSortOption.OLDEST:
                sort_criteria = [("created_at", 1)]
            else:
                sort_criteria = [("created_at", -1)]  # Default to newest

            # Get clubs with pagination
            clubs_cursor = club_collection.find(base_query).sort(sort_criteria).skip(skip).limit(page_size)
            clubs = await clubs_cursor.to_list(length=None)

            # Process clubs
            processed_clubs = []
            for club in clubs:
                club_id = str(club["_id"])
                moderator_status_info = self._get_moderator_status_info(club, user_id)
                club_item = await self._process_club_item(
                    club,
                    payments_collection,
                    membership_collection,
                    moderator_status_info,
                    user_id=user_id
                )
                if club_item:
                    processed_clubs.append(club_item)

            # Apply member_status filtering if specified
            if filters and filters.member_status:
                logger.info(f"Filtering clubs by member_status: {filters.member_status}")
                filtered_clubs = []
                for club in processed_clubs:
                    if club.member_combined_status == filters.member_status:
                        filtered_clubs.append(club)
                processed_clubs = filtered_clubs
                # Update total_count after filtering
                total_count = len(processed_clubs)
                total_pages = (total_count + page_size - 1) // page_size
                logger.info(f"Filtered to {len(processed_clubs)} clubs with member_status: {filters.member_status}")

            # Apply post-processing sorting for most_members option
            if sort_by == MyClubsSortOption.MOST_MEMBERS:
                logger.info("Applying post-processing sort by most members")
                processed_clubs.sort(key=lambda x: x.total_members, reverse=True)
                logger.info(f"Sorted clubs by member count: {[(c.club_name, c.total_members) for c in processed_clubs]}")

            # Calculate pagination flags
            has_next = page < total_pages
            has_previous = page > 1

            logger.info(f"Retrieved {len(processed_clubs)} moderator clubs for user {user_id}")

            # Add user role information to each club
            for club in processed_clubs:
                club.user_role = await self._determine_user_role_in_club(user_id, club.club_id)

            # Calculate totals
            total_members = sum(club.total_members for club in processed_clubs)
            total_moderators = sum(club.moderator_count for club in processed_clubs)

            return MyClubsResponse(
                clubs=processed_clubs,
                total_count=total_count,
                total_members=total_members,
                total_moderators=total_moderators,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=has_next,
                has_previous=has_previous
            )

        except Exception as e:
            logger.error(f"Error getting user moderator clubs: {e}")
            return None

    def _get_moderator_status_info(self, club: Dict, user_id: str) -> Optional[Dict]:
        """Get moderator's status information for a specific club"""
        try:
            # Check detailed_moderators array
            detailed_moderators = club.get("detailed_moderators", [])
            for moderator in detailed_moderators:
                if moderator.get("user_id") == user_id:
                    return {
                        "status": moderator.get("status", "active"),
                        "membership_status": moderator.get("status", "active"),  # For moderators, status and membership_status are the same
                    }

            return None

        except Exception as e:
            logger.error(f"Error getting moderator status info: {e}")
            return None