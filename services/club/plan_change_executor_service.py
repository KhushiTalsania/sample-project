"""
Plan Change Executor Service

This service handles the execution of scheduled plan changes.
It runs periodically to check for scheduled plan changes that need to be executed
and updates the user's active subscription to the new plan.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
from bson import ObjectId

from .db import get_club_collection, get_user_collection, get_membership_collection

# Configure logging
logger = logging.getLogger(__name__)

class PlanChangeExecutorService:
    """Service for executing scheduled plan changes"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
        self.membership_collection = get_membership_collection()
    
    async def execute_scheduled_plan_changes(self) -> Tuple[int, int]:
        """
        Execute all scheduled plan changes that are due
        
        Returns:
            Tuple of (successful_executions, failed_executions)
        """
        try:
            logger.info("🔄 Starting execution of scheduled plan changes")
            
            # Find all users with scheduled plan changes that are due
            now = datetime.now()
            users_with_scheduled_changes = await self._find_users_with_due_plan_changes(now)
            
            if not users_with_scheduled_changes:
                logger.info("✅ No scheduled plan changes to execute")
                return 0, 0
            
            logger.info(f"📋 Found {len(users_with_scheduled_changes)} users with scheduled plan changes")
            
            successful_executions = 0
            failed_executions = 0
            
            for user_data in users_with_scheduled_changes:
                try:
                    success = await self._execute_user_plan_changes(user_data)
                    if success:
                        successful_executions += 1
                        logger.info(f"✅ Successfully executed plan changes for user {user_data['user_id']}")
                    else:
                        failed_executions += 1
                        logger.error(f"❌ Failed to execute plan changes for user {user_data['user_id']}")
                except Exception as e:
                    failed_executions += 1
                    logger.error(f"❌ Error executing plan changes for user {user_data['user_id']}: {str(e)}")
            
            logger.info(f"🏁 Plan change execution completed: {successful_executions} successful, {failed_executions} failed")
            return successful_executions, failed_executions
            
        except Exception as e:
            logger.error(f"❌ Error in execute_scheduled_plan_changes: {str(e)}")
            return 0, 0
    
    async def _find_users_with_due_plan_changes(self, current_time: datetime) -> List[Dict]:
        """Find all users with scheduled plan changes that are due"""
        try:
            # Query users with scheduled plan changes where new_start_date <= current_time
            users = await self.user_collection.find({
                "clubs_joined": {
                    "$elemMatch": {
                        "status": "upcoming",
                        "join_date": {"$lte": current_time}
                    }
                }
            }).to_list(None)
            
            # Also query club_memberships collection for any scheduled plan changes
            memberships = await self.membership_collection.find({
                "status": "upcoming",
                "start_date": {"$lte": current_time}
            }).to_list(None)
            
            # Add memberships data to users for processing
            for membership in memberships:
                user_id = str(membership["user_id"])
                # Find the user in the users list, if not found, fetch the user
                user_found = False
                for user in users:
                    if str(user["_id"]) == user_id:
                        user_found = True
                        break
                
                if not user_found:
                    # Fetch user if not already in the list
                    user = await self.user_collection.find_one({"_id": membership["user_id"]})
                    if user:
                        users.append(user)
            
            return users
            
        except Exception as e:
            logger.error(f"Error finding users with due plan changes: {e}")
            return []
    
    async def _execute_user_plan_changes(self, user_data: Dict) -> bool:
        """Execute all due plan changes for a specific user"""
        try:
            user_id = str(user_data["_id"])
            clubs_joined = user_data.get("clubs_joined", [])
            
            # Find clubs with due plan changes
            clubs_to_update = []
            for club_data in clubs_joined:
                if (club_data.get("status") == "upcoming" and
                    club_data.get("join_date") <= datetime.now()):
                    
                    clubs_to_update.append({
                        "club_id": club_data.get("club_id"),
                        "club_data": club_data
                    })
            
            if not clubs_to_update:
                return True  # No changes to execute
            
            # Execute plan changes for each club
            all_successful = True
            for club_update in clubs_to_update:
                success = await self._execute_club_plan_change(user_id, club_update)
                if not success:
                    all_successful = False
            
            return all_successful
            
        except Exception as e:
            logger.error(f"Error executing user plan changes: {e}")
            return False
    
    async def _execute_club_plan_change(self, user_id: str, club_update: Dict) -> bool:
        """Execute plan change for a specific club"""
        try:
            club_id = club_update["club_id"]
            club_data = club_update["club_data"]
            
            new_pricing_plan = club_data["pricing_plan"]
            new_price = club_data["amount_paid"]
            payment_intent_id = club_data["payment_id"]
            new_start_date = club_data["join_date"]
            new_end_date = club_data["end_date"]
            
            # Update user's clubs_joined array - change status from "upcoming" to "active"
            user_update_result = await self.user_collection.update_one(
                {
                    "_id": ObjectId(user_id),
                    "clubs_joined.club_id": club_id,
                    "clubs_joined.payment_id": payment_intent_id,
                    "clubs_joined.status": "upcoming"
                },
                {
                    "$set": {
                        "clubs_joined.$.status": "active",
                        "clubs_joined.$.membership_status": "active",
                        "clubs_joined.$.updated_at": datetime.now(),
                        "clubs_joined.$.executed_at": datetime.now()
                    }
                }
            )
            
            if user_update_result.modified_count == 0:
                logger.error(f"Failed to update user's club membership for club {club_id}")
                return False
            
            # Update club's paid_members array - change status from "upcoming" to "active"
            club_update_result = await self.club_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "paid_members.user_id": user_id,
                    "paid_members.payment_id": payment_intent_id,
                    "paid_members.status": "upcoming"
                },
                {
                    "$set": {
                        "paid_members.$.status": "active",
                        "paid_members.$.membership_status": "active",
                        "paid_members.$.updated_at": datetime.now(),
                        "paid_members.$.executed_at": datetime.now()
                    }
                }
            )
            
            if club_update_result.modified_count == 0:
                logger.error(f"Failed to update club's member record for user {user_id}")
                return False
            
            # Update club_memberships collection - change status from "upcoming" to "active"
            membership_update_result = await self.membership_collection.update_one(
                {
                    "user_id": ObjectId(user_id),
                    "club_id": ObjectId(club_id),
                    "payment_id": payment_intent_id,
                    "status": "upcoming"
                },
                {
                    "$set": {
                        "status": "active",
                        "membership_status": "active",
                        "updated_at": datetime.now(),
                        "executed_at": datetime.now()
                    }
                }
            )
            
            if membership_update_result.modified_count == 0:
                logger.warning(f"Failed to update club_memberships record for user {user_id} in club {club_id}")
                # Don't fail the entire operation, just log the warning
            
            logger.info(f"✅ Successfully executed plan change for user {user_id} in club {club_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error executing club plan change: {e}")
            return False
    
    async def get_scheduled_plan_changes_summary(self) -> Dict[str, Any]:
        """Get summary of all scheduled plan changes"""
        try:
            now = datetime.now()
            
            # Count scheduled changes by status in users collection
            upcoming_users_count = await self.user_collection.count_documents({
                "clubs_joined.status": "upcoming"
            })
            
            active_users_count = await self.user_collection.count_documents({
                "clubs_joined.status": "active"
            })
            
            # Count scheduled changes by status in club_memberships collection
            upcoming_memberships_count = await self.membership_collection.count_documents({
                "status": "upcoming"
            })
            
            active_memberships_count = await self.membership_collection.count_documents({
                "status": "active"
            })
            
            # Combine counts
            upcoming_count = upcoming_users_count + upcoming_memberships_count
            active_count = active_users_count + active_memberships_count
            
            # Count changes due today in users collection
            due_today_users_count = await self.user_collection.count_documents({
                "clubs_joined": {
                    "$elemMatch": {
                        "status": "upcoming",
                        "join_date": {
                            "$gte": now.replace(hour=0, minute=0, second=0, microsecond=0),
                            "$lt": now.replace(hour=23, minute=59, second=59, microsecond=999999)
                        }
                    }
                }
            })
            
            # Count changes due today in club_memberships collection
            due_today_memberships_count = await self.membership_collection.count_documents({
                "status": "upcoming",
                "start_date": {
                    "$gte": now.replace(hour=0, minute=0, second=0, microsecond=0),
                    "$lt": now.replace(hour=23, minute=59, second=59, microsecond=999999)
                }
            })
            
            # Count overdue changes in users collection
            overdue_users_count = await self.user_collection.count_documents({
                "clubs_joined": {
                    "$elemMatch": {
                        "status": "upcoming",
                        "join_date": {"$lt": now}
                    }
                }
            })
            
            # Count overdue changes in club_memberships collection
            overdue_memberships_count = await self.membership_collection.count_documents({
                "status": "upcoming",
                "start_date": {"$lt": now}
            })
            
            # Combine counts
            due_today_count = due_today_users_count + due_today_memberships_count
            overdue_count = overdue_users_count + overdue_memberships_count
            
            return {
                "total_scheduled": upcoming_count + active_count,
                "upcoming_changes": upcoming_count,
                "active_changes": active_count,
                "due_today": due_today_count,
                "overdue": overdue_count,
                "last_checked": now.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting scheduled plan changes summary: {e}")
            return {
                "total_scheduled": 0,
                "upcoming_changes": 0,
                "active_changes": 0,
                "due_today": 0,
                "overdue": 0,
                "last_checked": datetime.now().isoformat(),
                "error": str(e)
            }
