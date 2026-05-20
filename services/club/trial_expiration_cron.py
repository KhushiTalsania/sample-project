"""
Trial Membership Expiration Cron Job Service

This service runs periodically to check for expired trial club memberships
and updates their status across all collections.

Expiration Logic:
- Each trial club has 7 days validity from join date
- After 7 days, membership status changes to "expired"
- Updates are made in:
  1. membership collection
  2. trial_club_access collection
  3. clubs collection (members array)
  4. users collection (clubs_joined array)
"""

from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import logging
import asyncio

from .db import (
    get_club_collection,
    get_user_collection,
    get_membership_collection,
    get_trial_club_access_collection,
)

logger = logging.getLogger(__name__)


class TrialExpirationCronService:
    """Service to handle trial membership expiration"""

    def __init__(self):
        self.logger = logger

    async def check_and_expire_trial_memberships(self):
        """
        Main cron job function to check and expire trial memberships
        Runs periodically (e.g., every hour or daily)
        """
        try:
            self.logger.info("🔄 Starting trial membership expiration check...")
            
            now = datetime.now(timezone.utc)
            
            # Get all trial club access records that are active but expired
            access_collection = get_trial_club_access_collection()
            expired_accesses = await access_collection.find({
                "is_access_active": True,
                "access_expires_date": {"$lte": now}
            }).to_list(None)
            
            if not expired_accesses:
                self.logger.info("✅ No expired trial memberships found")
                return {
                    "success": True,
                    "message": "No expired trial memberships",
                    "expired_count": 0
                }
            
            self.logger.info(f"⚠️ Found {len(expired_accesses)} expired trial memberships")
            
            # Process each expired access
            expired_count = 0
            for access in expired_accesses:
                try:
                    success = await self._expire_trial_membership(access)
                    if success:
                        expired_count += 1
                except Exception as e:
                    self.logger.error(f"Error expiring membership for user {access.get('user_id')}, club {access.get('club_id')}: {e}")
                    continue
            
            self.logger.info(f"✅ Successfully expired {expired_count} trial memberships")
            
            return {
                "success": True,
                "message": f"Expired {expired_count} trial memberships",
                "expired_count": expired_count
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error in trial expiration cron job: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "expired_count": 0
            }

    async def _expire_trial_membership(self, access: dict) -> bool:
        """
        Expire a single trial membership by updating all related collections
        
        Args:
            access: Trial club access document
            
        Returns:
            bool: Success status
        """
        try:
            user_id = access.get("user_id")
            club_id = access.get("club_id")
            club_name = access.get("club_name", "")
            
            self.logger.info(f"⏰ Expiring trial membership: user {user_id}, club {club_id}")
            
            now = datetime.now(timezone.utc)
            
            # Update all collections in parallel for better performance
            await asyncio.gather(
                self._update_trial_club_access(user_id, club_id, now),
                self._update_membership_collection(user_id, club_id, now),
                self._update_club_members_array(club_id, user_id, now),
                self._update_user_clubs_array(user_id, club_id, now),
                return_exceptions=True
            )
            
            self.logger.info(f"✅ Successfully expired trial membership: user {user_id}, club {club_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error expiring trial membership: {e}")
            return False

    async def _update_trial_club_access(self, user_id: str, club_id: str, now: datetime):
        """Update trial_club_access collection - mark as inactive"""
        try:
            access_collection = get_trial_club_access_collection()
            result = await access_collection.update_one(
                {
                    "user_id": user_id,
                    "club_id": club_id
                },
                {
                    "$set": {
                        "is_access_active": False,
                        "status": "expired",
                        "membership_status": "expired",
                        "expired_at": now,
                        "updated_at": now
                    }
                }
            )
            
            if result.modified_count > 0:
                self.logger.info(f"✅ Updated trial_club_access for user {user_id}, club {club_id}")
            
        except Exception as e:
            self.logger.error(f"Error updating trial_club_access: {e}")
            raise

    async def _update_membership_collection(self, user_id: str, club_id: str, now: datetime):
        """Update membership collection - change status to expired"""
        try:
            membership_collection = get_membership_collection()
            result = await membership_collection.update_one(
                {
                    "user_id": user_id,
                    "club_id": club_id,
                    "is_trial_membership": True
                },
                {
                    "$set": {
                        "subscription_status": "expired",
                        "membership_status": "expired",
                        "is_access_active": False,
                        "expired_at": now,
                        "updated_at": now
                    }
                }
            )
            
            if result.modified_count > 0:
                self.logger.info(f"✅ Updated membership collection for user {user_id}, club {club_id}")
            
        except Exception as e:
            self.logger.error(f"Error updating membership collection: {e}")
            raise

    async def _update_club_members_array(self, club_id: str, user_id: str, now: datetime):
        """Update clubs collection - change member status to expired in members array"""
        try:
            club_collection = get_club_collection()
            
            # Update in members array (trial members)
            result = await club_collection.update_one(
                {
                    "_id": ObjectId(club_id),
                    "members.user_id": user_id
                },
                {
                    "$set": {
                        "members.$.status": "expired",
                        "members.$.membership_status": "expired",
                        "members.$.is_active": False,
                        "members.$.expired_at": now,
                        "members.$.updated_at": now
                    }
                }
            )
            
            if result.modified_count > 0:
                self.logger.info(f"✅ Updated club members array for club {club_id}, user {user_id}")
            
        except Exception as e:
            self.logger.error(f"Error updating club members array: {e}")
            raise

    async def _update_user_clubs_array(self, user_id: str, club_id: str, now: datetime):
        """Update users collection - change club status to expired in clubs_joined array"""
        try:
            user_collection = get_user_collection()
            
            # Update in clubs_joined array
            result = await user_collection.update_one(
                {
                    "_id": ObjectId(user_id),
                    "clubs_joined.club_id": club_id
                },
                {
                    "$set": {
                        "clubs_joined.$.status": "expired",
                        "clubs_joined.$.membership_status": "expired",
                        "clubs_joined.$.is_active": False,
                        "clubs_joined.$.expired_at": now,
                        "clubs_joined.$.updated_at": now
                    }
                }
            )
            
            if result.modified_count > 0:
                self.logger.info(f"✅ Updated user clubs_joined array for user {user_id}, club {club_id}")
            
        except Exception as e:
            self.logger.error(f"Error updating user clubs_joined array: {e}")
            raise

    async def get_expiring_soon_memberships(self, hours: int = 24) -> List[Dict]:
        """
        Get trial memberships that will expire soon (within specified hours)
        Useful for sending notifications to users
        
        Args:
            hours: Number of hours to look ahead
            
        Returns:
            List of memberships expiring soon
        """
        try:
            now = datetime.now(timezone.utc)
            expiry_threshold = now + timedelta(hours=hours)
            
            access_collection = get_trial_club_access_collection()
            expiring_soon = await access_collection.find({
                "is_access_active": True,
                "access_expires_date": {
                    "$gt": now,
                    "$lte": expiry_threshold
                }
            }).to_list(None)
            
            return expiring_soon
            
        except Exception as e:
            self.logger.error(f"Error getting expiring soon memberships: {e}")
            return []

    async def check_user_club_access(self, user_id: str, club_id: str) -> Dict:
        """
        Check if user has active access to a club
        Returns status and message
        
        Args:
            user_id: User's ID
            club_id: Club's ID
            
        Returns:
            Dict with access status and message
        """
        try:
            access_collection = get_trial_club_access_collection()
            now = datetime.now(timezone.utc)
            
            access = await access_collection.find_one({
                "user_id": user_id,
                "club_id": club_id
            })
            
            if not access:
                return {
                    "has_access": False,
                    "status": "no_membership",
                    "message": "You are not a member of this club"
                }
            
            # Check if expired
            if access.get("access_expires_date") <= now:
                return {
                    "has_access": False,
                    "status": "expired",
                    "membership_status": "expired",
                    "message": "Your 7-day trial access has expired. Please upgrade to a paid plan to continue accessing this club.",
                    "expired_at": access.get("access_expires_date"),
                    "club_name": access.get("club_name", "")
                }
            
            # Active access
            days_remaining = (access.get("access_expires_date") - now).days
            return {
                "has_access": True,
                "status": "active",
                "message": f"You have active access. {days_remaining} days remaining.",
                "expires_at": access.get("access_expires_date"),
                "days_remaining": days_remaining
            }
            
        except Exception as e:
            self.logger.error(f"Error checking user club access: {e}")
            return {
                "has_access": False,
                "status": "error",
                "message": f"Error checking access: {str(e)}"
            }


# Singleton instance
_trial_expiration_service = None


def get_trial_expiration_service() -> TrialExpirationCronService:
    """Get or create trial expiration service instance"""
    global _trial_expiration_service
    if _trial_expiration_service is None:
        _trial_expiration_service = TrialExpirationCronService()
    return _trial_expiration_service
