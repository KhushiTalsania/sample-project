from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import logging
import asyncio
import os

from .db import (
    get_club_collection, get_user_collection, get_membership_collection,
    get_trial_membership_collection, get_trial_club_access_collection
)
from .models import (
    JoinTrialFreeRequest, JoinTrialFreeResponse, TrialClubAccess,
    TrialMembershipStatus, TrialLimits
)
from .trial_service import get_trial_membership_status, is_user_trial_member
from .membership_service import add_member_to_club

logger = logging.getLogger(__name__)

# Trial configuration
TRIAL_LIMITS = TrialLimits(
    max_clubs=4,
    trial_duration_days=30,
    refund_period_days=7,
    groups_per_week=1
)

# Testing configuration - set TRIAL_TESTING_MODE=true to enable immediate expiration
TRIAL_TESTING_MODE = os.getenv('TRIAL_TESTING_MODE', 'false').lower() == 'true'
TRIAL_DAYS_FOR_TESTING = int(os.getenv('TRIAL_DAYS_FOR_TESTING', '0'))  # 0 = immediate expiry for testing

# Force testing mode for immediate expiration (TEMPORARY - for testing only)
FORCE_TESTING_MODE = True  # Set to True to force immediate expiration
FORCE_TESTING_DAYS = 0     # Set to 0 for immediate expiry

def get_trial_club_access_collection():
    """Get trial club access tracking collection"""
    from .db import db
    return db["trial_club_access"]

class JoinTrialFreeService:
    """Service for handling trial-free club joining"""
    
    def __init__(self):
        self.trial_limits = TRIAL_LIMITS
    
    async def join_club_trial_free(self, user_id: str, request: JoinTrialFreeRequest) -> Tuple[bool, Optional[JoinTrialFreeResponse], Optional[str]]:
        """
        Join a club with trial membership (free for 7 days per club)
        
        Args:
            user_id: User's ID
            request: Join trial free request
            
        Returns:
            Tuple[bool, Optional[JoinTrialFreeResponse], Optional[str]]: (success, response_data, error_message)
        """
        try:
            logger.info(f"Processing trial-free join request for user {user_id}, club {request.club_id}")
            
            # OPTIMIZATION: Get all required data in parallel to reduce DB calls
            user_trial_data, club_data, membership_check = await asyncio.gather(
                self._get_user_trial_data_optimized(user_id),
                self._validate_club_optimized(request.club_id),
                self._is_user_member_of_club_optimized(user_id, request.club_id),
                return_exceptions=True
            )
            
            # Handle exceptions from parallel calls
            if isinstance(user_trial_data, Exception):
                return False, None, f"Error getting user trial data: {str(user_trial_data)}"
            if isinstance(club_data, Exception):
                return False, None, f"Error validating club: {str(club_data)}"
            if isinstance(membership_check, Exception):
                return False, None, f"Error checking membership: {str(membership_check)}"
            
            # Extract data from optimized calls
            is_trial_member, trial_status = user_trial_data
            club_validation_success, club_validation_error, club = club_data
            is_already_member = membership_check
            
            # Validate user has trial membership
            if not is_trial_member:
                return False, None, "User must have active trial membership to use this feature"
            
            if not trial_status.is_trial_active:
                return False, None, "Trial membership is not active"
            
            # Check if user can join more clubs
            if trial_status.clubs_joined_count >= self.trial_limits.max_clubs:
                return False, None, f"Maximum club limit reached ({self.trial_limits.max_clubs} clubs)"
            
            # Validate club exists and get club details
            if not club_validation_success:
                return False, None, club_validation_error
            
            # Check if user is already a member of this club
            if is_already_member:
                return False, None, "User is already a member of this club"
            
            # OPTIMIZATION: Use transaction for data consistency
            try:
                client = self._get_database_client()
                async with client.start_session() as session:
                    async with session.start_transaction():
                        # Create trial club access
                        access_creation = await self._create_trial_club_access_optimized(user_id, club, session)
                        if not access_creation[0]:
                            return False, None, access_creation[1]
                        
                        # Get access expiry date from the created access
                        access_expires = access_creation[2].access_expires_date
                        
                        # OPTIMIZATION: Batch update operations
                        await self._batch_update_operations(
                            user_id, str(club["_id"]), access_expires, session
                        )
            except Exception as transaction_error:
                logger.warning(f"Transaction not supported, falling back to non-transactional mode: {transaction_error}")
                # Fallback to non-transactional mode
                access_creation = await self._create_trial_club_access_optimized(user_id, club, None)
                if not access_creation[0]:
                    return False, None, access_creation[1]
                
                # Get access expiry date from the created access
                access_expires = access_creation[2].access_expires_date
                
                # OPTIMIZATION: Batch update operations
                await self._batch_update_operations(
                    user_id, str(club["_id"]), access_expires, None
                )
            
            # OPTIMIZATION: Get updated data in parallel
            updated_trial_status, clubs_joined = await asyncio.gather(
                get_trial_membership_status(user_id),
                self._get_user_trial_clubs(user_id),
                return_exceptions=True
            )
            
            # Handle exceptions
            if isinstance(updated_trial_status, Exception):
                logger.warning(f"Error getting updated trial status: {updated_trial_status}")
                updated_trial_status = trial_status  # Use previous status as fallback
            if isinstance(clubs_joined, Exception):
                logger.warning(f"Error getting clubs joined: {clubs_joined}")
                clubs_joined = []
            
            # Create response with expiration info
            expiry_date = access_creation[2].access_expires_date
            expiry_formatted = expiry_date.strftime("%B %d, %Y")
            
            response = JoinTrialFreeResponse(
                success=True,
                message=(
                    f"Successfully joined club '{club['name']}' with 7-day trial access! "
                    f"Your access will expire on {expiry_formatted}. "
                    f"After 7 days, you can upgrade to a paid plan to continue accessing this club."
                ),
                club_access=access_creation[2],
                trial_status=updated_trial_status,
                clubs_joined=clubs_joined,
                can_join_more=updated_trial_status.clubs_remaining > 0,
                days_remaining_in_trial=updated_trial_status.days_remaining
            )
            
            logger.info(f"Successfully processed trial-free join for user {user_id}, club {request.club_id}")
            return True, response, None
            
        except Exception as e:
            error_msg = f"Error processing trial-free join: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
    
    async def _validate_club(self, club_name_based_id: str) -> Tuple[bool, Optional[str], Optional[dict]]:
        """
        Validate that club exists and is active
        
        Returns:
            Tuple[bool, Optional[str], Optional[dict]]: (is_valid, error_message, club_data)
        """
        try:
            club_collection = get_club_collection()
            club = await club_collection.find_one({"name_based_id": club_name_based_id})
            
            if not club:
                return False, f"Club '{club_name_based_id}' not found", None
            
            if not club.get("is_active", True):
                return False, f"Club '{club_name_based_id}' is not active", None
            
            return True, None, club
            
        except Exception as e:
            logger.error(f"Error validating club {club_name_based_id}: {e}")
            return False, f"Error validating club: {str(e)}", None
    
    async def _is_user_member_of_club(self, user_id: str, club_id: str) -> bool:
        """Check if user is already a member of the club"""
        try:
            membership_collection = get_membership_collection()
            existing_membership = await membership_collection.find_one({
                "user_id": user_id,
                "club_id": club_id,
                "subscription_status": {"$in": ["active", "trial"]}
            })
            
            return existing_membership is not None
            
        except Exception as e:
            logger.error(f"Error checking club membership: {e}")
            return False
    
    async def _create_trial_club_access(self, user_id: str, club: dict) -> Tuple[bool, Optional[str], Optional[TrialClubAccess]]:
        """
        Create trial club access record
        
        Returns:
            Tuple[bool, Optional[str], Optional[TrialClubAccess]]: (success, error_message, access_data)
        """
        try:
            now = datetime.now(timezone.utc)
            access_expires = now + timedelta(days=7)  # 7 days access
            
            # Create trial club access document
            access_doc = {
                "user_id": user_id,
                "club_id": str(club["_id"]),
                "club_name": club.get("name", ""),
                "club_name_based_id": club.get("name_based_id", ""),
                "captain_name": club.get("captain_details", {}).get("full_name", "Unknown Captain"),
                "join_date": now,
                "access_expires_date": access_expires,
                "is_access_active": True,
                "created_at": now,
                "updated_at": now
            }
            
            # Create membership record for trial member
            membership_collection = get_membership_collection()
            membership_doc = {
                "user_id": user_id,
                "club_id": str(club["_id"]),
                "pricing_plan": "trial",
                "subscription_status": "trial",
                "is_trial_membership": True,
                "trial_join_date": now,
                "joined_date": now,
                "expires_date": access_expires,
                "payment_id": None,
                "amount_paid": 0.0,
                "refund_eligible": False,
                "refund_deadline": None,
                "created_at": now,
                "updated_at": now
            }
            
            membership_result = await membership_collection.insert_one(membership_doc)
            
            if not membership_result.inserted_id:
                return False, "Failed to create membership record", None
            
            # Add member to club using membership service (updates both club and user)
            # This handles adding to club's members array and user's clubs_joined array
            add_member_result = await add_member_to_club(
                user_id=user_id,
                club_id=str(club["_id"]),
                pricing_plan="trial",
                is_trial=True,
                membership_status="active",  # Set to active for trial members
                payment_id=None,
                amount_paid=0.0,
                end_date=access_expires
            )
            
            if not add_member_result:
                return False, "Failed to add member to club", None
            
            # Insert into trial club access collection for tracking (separate from membership)
            access_collection = get_trial_club_access_collection()
            result = await access_collection.insert_one(access_doc)
            
            if not result.inserted_id:
                logger.warning(f"Failed to create trial club access record, but membership was created successfully")
                # Don't fail the entire operation if trial access record creation fails
            
            # Update trial membership record
            trial_collection = get_trial_membership_collection()
            await trial_collection.update_one(
                {"user_id": user_id},
                {
                    "$push": {"clubs_joined": str(club["_id"])},
                    "$set": {"updated_at": now}
                }
            )
            
            # Create TrialClubAccess object
            access_data = TrialClubAccess(
                club_id=str(club["_id"]),
                club_name=club.get("name", ""),
                club_name_based_id=club.get("name_based_id", ""),
                captain_name=club.get("captain_details", {}).get("full_name", "Unknown Captain"),
                join_date=now,
                access_expires_date=access_expires,
                is_access_active=True
            )
            
            logger.info(f"Created trial club access for user {user_id}, club {club.get('name_based_id')}")
            return True, None, access_data
            
        except Exception as e:
            logger.error(f"Error creating trial club access: {e}")
            return False, f"Error creating trial club access: {str(e)}", None
    
    async def _update_club_member_count(self, club_id: str):
        """Update club member count based on actual arrays in club document"""
        try:
            club_collection = get_club_collection()
            
            # Get the club document to count from actual arrays
            club = await club_collection.find_one({"_id": ObjectId(club_id)})
            if not club:
                logger.error(f"Club {club_id} not found for count update")
                return
            
            # Count members from actual arrays
            paid_members = club.get("paid_members", [])
            members = club.get("members", [])
            
            paid_member_count = len(paid_members)
            member_count = len(members)  # Trial/free members
            total_members = paid_member_count + member_count
            
            # Update club member counts
            await club_collection.update_one(
                {"_id": ObjectId(club_id)},
                {
                    "$set": {
                        "member_count": member_count,  # Free/trial members
                        "paid_member_count": paid_member_count,  # Paid members
                        "total_members": total_members,  # Total = member_count + paid_member_count
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"Updated member counts for club {club_id}: trial={member_count}, paid={paid_member_count}, total={total_members}")
            
        except Exception as e:
            logger.error(f"Error updating club member count: {e}")
    
    async def _update_member_club_count(self, user_id: str):
        """Update member's club_count in auth database - ensures it becomes 1 and stays 1"""
        try:
            # Try to import auth service functions first
            try:
                import sys
                import os
                auth_service_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'betting_auth_service', 'auth')
                if auth_service_path not in sys.path:
                    sys.path.append(auth_service_path)
                
                from utils import update_user_club_count
                
                # For members, club_count should be 1 if they have joined any clubs
                await update_user_club_count(user_id, 1)
                logger.info(f"👤 Updated member {user_id} club_count to 1 via auth service")
                
            except ImportError as import_error:
                logger.warning(f"Could not import auth service functions: {import_error}")
                # Fallback: try to update directly in auth database
                try:
                    from motor.motor_asyncio import AsyncIOMotorClient
                    import os
                    
                    # Get auth database connection
                    auth_db_url = os.getenv('MONGO_URL', 'mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main')
                    auth_client = AsyncIOMotorClient(auth_db_url)
                    auth_db = auth_client.get_database('betting_main')
                    auth_users_collection = auth_db['users']
                    
                    # Update club_count for member to 1
                    now = datetime.now(timezone.utc)
                    result = await auth_users_collection.update_one(
                        {"_id": ObjectId(user_id)},
                        {
                            "$set": {
                                "club_count": 1,
                                "updated_at": now
                            }
                        }
                    )
                    
                    if result.modified_count > 0:
                        logger.info(f"👤 Updated member {user_id} club_count to 1 (direct database update)")
                    else:
                        logger.warning(f"👤 No document updated for member {user_id} club_count")
                    
                except Exception as direct_error:
                    logger.error(f"Could not update member club_count directly: {direct_error}")
            except Exception as update_error:
                logger.error(f"Error updating member club_count via auth service: {update_error}")
                
        except Exception as e:
            logger.error(f"Error in _update_member_club_count: {e}")
    
    async def _update_user_club_counts(self, user_id: str, is_paid: bool = False):
        """Update user's club counts in auth database"""
        try:
            # Try to import auth service functions first
            try:
                import sys
                import os
                auth_service_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'betting_auth_service', 'auth')
                if auth_service_path not in sys.path:
                    sys.path.append(auth_service_path)
                
                from utils import update_user_club_count
                
                # Update club_count to 1 (stays 1 forever for members)
                await update_user_club_count(user_id, 1)
                logger.info(f"Updated user {user_id} club_count to 1 via auth service")
                
            except ImportError as import_error:
                logger.warning(f"Could not import auth service functions: {import_error}")
                # Fallback: try to update directly in auth database
                try:
                    from motor.motor_asyncio import AsyncIOMotorClient
                    import os
                    
                    # Get auth database connection
                    auth_db_url = os.getenv('MONGO_URL', 'mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main')
                    auth_client = AsyncIOMotorClient(auth_db_url)
                    auth_db = auth_client.get_database('betting_main')
                    auth_users_collection = auth_db['users']
                    
                    # Update club counts using proper MongoDB operations
                    now = datetime.utcnow()
                    
                    # Build update operations
                    update_operations = {
                        "$set": {
                            "club_count": 1,
                            "updated_at": now
                        }
                    }
                    
                    # Add increment operations
                    inc_operations = {}
                    if is_paid:
                        inc_operations["paid_clubs_joined"] = 1
                    inc_operations["total_clubs_joined"] = 1
                    
                    if inc_operations:
                        update_operations["$inc"] = inc_operations
                    
                    result = await auth_users_collection.update_one(
                        {"_id": ObjectId(user_id)},
                        update_operations
                    )
                    
                    if result.modified_count > 0:
                        logger.info(f"Updated user {user_id} club counts (direct database update)")
                    else:
                        logger.warning(f"No document updated for user {user_id} club counts")
                    
                except Exception as direct_error:
                    logger.error(f"Could not update user club counts directly: {direct_error}")
            except Exception as update_error:
                logger.error(f"Error updating user club counts via auth service: {update_error}")
                
        except Exception as e:
            logger.error(f"Error in _update_user_club_counts: {e}")
    
    async def _get_user_trial_clubs(self, user_id: str) -> List[TrialClubAccess]:
        """Get all clubs joined by user during trial"""
        try:
            access_collection = get_trial_club_access_collection()
            access_records = await access_collection.find({
                "user_id": user_id,
                "is_access_active": True
            }).to_list(None)
            
            clubs_joined = []
            for record in access_records:
                # Check if access is still valid (not expired)
                now = datetime.now(timezone.utc)
                is_active = record.get("access_expires_date", now) > now
                
                club_access = TrialClubAccess(
                    club_id=record.get("club_id", ""),
                    club_name=record.get("club_name", ""),
                    club_name_based_id=record.get("club_name_based_id", ""),
                    captain_name=record.get("captain_name", "Unknown Captain"),
                    join_date=record.get("join_date", now),
                    access_expires_date=record.get("access_expires_date", now),
                    is_access_active=is_active
                )
                clubs_joined.append(club_access)
            
            return clubs_joined
            
        except Exception as e:
            logger.error(f"Error getting user trial clubs: {e}")
            return []
    
    async def check_trial_club_access(self, user_id: str, club_id: str) -> bool:
        """
        Check if user has active trial access to a specific club
        
        Args:
            user_id: User's ID
            club_id: Club's ID
            
        Returns:
            bool: True if user has active access, False otherwise
        """
        try:
            access_collection = get_trial_club_access_collection()
            now = datetime.now(timezone.utc)
            
            access_record = await access_collection.find_one({
                "user_id": user_id,
                "club_id": club_id,
                "is_access_active": True,
                "access_expires_date": {"$gt": now}
            })
            
            return access_record is not None
            
        except Exception as e:
            logger.error(f"Error checking trial club access: {e}")
            return False
    
    async def get_user_trial_status(self, user_id: str) -> Tuple[bool, Optional[JoinTrialFreeResponse], Optional[str]]:
        """
        Get user's trial status and joined clubs
        
        Args:
            user_id: User's ID
            
        Returns:
            Tuple[bool, Optional[JoinTrialFreeResponse], Optional[str]]: (success, response_data, error_message)
        """
        try:
            # Get trial membership status
            trial_status = await get_trial_membership_status(user_id)
            
            # Get all joined clubs
            clubs_joined = await self._get_user_trial_clubs(user_id)
            
            # Create response
            response = JoinTrialFreeResponse(
                success=True,
                message="Trial status retrieved successfully",
                club_access=None,
                trial_status=trial_status,
                clubs_joined=clubs_joined,
                can_join_more=trial_status.clubs_remaining > 0,
                days_remaining_in_trial=trial_status.days_remaining
            )
            
            return True, response, None
            
        except Exception as e:
            error_msg = f"Error getting trial status: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
    
    # OPTIMIZATION METHODS - Maintain exact same logic but improve performance
    
    async def _get_user_trial_data_optimized(self, user_id: str) -> Tuple[bool, Optional[object]]:
        """Get user trial data in optimized way - same logic as original"""
        try:
            # Same logic as original but optimized
            is_trial_member = await is_user_trial_member(user_id)
            if not is_trial_member:
                return False, None
            
            trial_status = await get_trial_membership_status(user_id)
            return True, trial_status
            
        except Exception as e:
            logger.error(f"Error getting user trial data: {e}")
            return False, None
    
    async def _validate_club_optimized(self, club_name_based_id: str) -> Tuple[bool, Optional[str], Optional[dict]]:
        """Validate club in optimized way - same logic as original"""
        try:
            club_collection = get_club_collection()
            club = await club_collection.find_one({"name_based_id": club_name_based_id})
            
            if not club:
                return False, f"Club '{club_name_based_id}' not found", None
            
            if not club.get("is_active", True):
                return False, f"Club '{club_name_based_id}' is not active", None
            
            return True, None, club
            
        except Exception as e:
            logger.error(f"Error validating club {club_name_based_id}: {e}")
            return False, f"Error validating club: {str(e)}", None
    
    async def _is_user_member_of_club_optimized(self, user_id: str, club_name_based_id: str) -> bool:
        """Check membership in optimized way - same logic as original"""
        try:
            # First get club ID from name_based_id
            club_collection = get_club_collection()
            club = await club_collection.find_one({"name_based_id": club_name_based_id})
            if not club:
                return False
            
            club_id = str(club["_id"])
            
            # Check membership
            membership_collection = get_membership_collection()
            existing_membership = await membership_collection.find_one({
                "user_id": user_id,
                "club_id": club_id,
                "subscription_status": {"$in": ["active", "trial"]}
            })
            
            return existing_membership is not None
            
        except Exception as e:
            logger.error(f"Error checking club membership: {e}")
            return False
    
    def _get_database_client(self):
        """Get database client for transactions"""
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            import os
            
            auth_db_url = os.getenv('MONGO_URL', 'mongodb+srv://techticpriyaagrawal:dmfx5vrr8HKF9FHE@cluster0.77bgqum.mongodb.net/betting_main')
            if not auth_db_url:
                raise ValueError("MONGO_URL environment variable not set")
            
            client = AsyncIOMotorClient(auth_db_url)
            return client
        except Exception as e:
            logger.error(f"Error getting database client: {e}")
            raise
    
    async def _create_trial_club_access_optimized(self, user_id: str, club: dict, session) -> Tuple[bool, Optional[str], Optional[TrialClubAccess]]:
        """Create trial club access with transaction support - same logic as original"""
        try:
            now = datetime.now(timezone.utc)
            # print(TRIAL_TESTING_MODE,TRIAL_DAYS_FOR_TESTING,"yes TRIAL_TESTING_MODETRIAL_DAYS_FOR_TESTING")
            access_expires = now + timedelta(days=7)  # 7 days access

            # # TESTING MODE: Allow immediate expiration for testing
            # if TRIAL_TESTING_MODE or FORCE_TESTING_MODE:
            #     trial_days = TRIAL_DAYS_FOR_TESTING if TRIAL_TESTING_MODE else FORCE_TESTING_DAYS
            #     access_expires = now + timedelta(days=trial_days)  # Use testing days (can be 0 for immediate expiry)
            #     print(f"🔥 FORCED TESTING MODE: Trial access set to {trial_days} days (expires: {access_expires})")
            #     logger.warning(f"🔥 FORCED TESTING MODE: Trial access set to {trial_days} days (expires: {access_expires})")
            # else:
            #     access_expires = now + timedelta(days=7)  # 7 days access (production)
            
            # Create trial club access document
            access_doc = {
                "user_id": user_id,
                "club_id": str(club["_id"]),
                "club_name": club.get("name", ""),
                "club_name_based_id": club.get("name_based_id", ""),
                "captain_name": club.get("captain_details", {}).get("full_name", "Unknown Captain"),
                "join_date": now,
                "access_expires_date": access_expires,
                "is_access_active": True,
                "created_at": now,
                "updated_at": now
            }
            
            # Create membership record for trial member
            membership_collection = get_membership_collection()
            membership_doc = {
                "user_id": user_id,
                "club_id": str(club["_id"]),
                "pricing_plan": "trial",
                "subscription_status": "trial",
                "is_trial_membership": True,
                "trial_join_date": now,
                "joined_date": now,
                "expires_date": access_expires,
                "payment_id": None,
                "amount_paid": 0.0,
                "refund_eligible": False,
                "refund_deadline": None,
                "created_at": now,
                "updated_at": now
            }
            
            # Insert membership record with session (if available)
            if session:
                membership_result = await membership_collection.insert_one(membership_doc, session=session)
            else:
                membership_result = await membership_collection.insert_one(membership_doc)
            
            if not membership_result.inserted_id:
                return False, "Failed to create membership record", None
            
            # Add member to club using membership service (updates both club and user)
            from .membership_service import add_member_to_club
            add_member_result = await add_member_to_club(
                user_id=user_id,
                club_id=str(club["_id"]),
                pricing_plan="trial",
                is_trial=True,
                membership_status="active",  # Set to active for trial members
                payment_id=None,
                amount_paid=0.0,
                end_date=access_expires
            )
            
            if not add_member_result:
                return False, "Failed to add member to club", None
            
            # Insert into trial club access collection for tracking (separate from membership)
            access_collection = get_trial_club_access_collection()
            if session:
                result = await access_collection.insert_one(access_doc, session=session)
            else:
                result = await access_collection.insert_one(access_doc)
            
            if not result.inserted_id:
                logger.warning(f"Failed to create trial club access record, but membership was created successfully")
                # Don't fail the entire operation if trial access record creation fails
            
            # Update trial membership record
            trial_collection = get_trial_membership_collection()
            if session:
                await trial_collection.update_one(
                    {"user_id": user_id},
                    {
                        "$push": {"clubs_joined": str(club["_id"])},
                        "$set": {"updated_at": now}
                    },
                    session=session
                )
            else:
                await trial_collection.update_one(
                    {"user_id": user_id},
                    {
                        "$push": {"clubs_joined": str(club["_id"])},
                        "$set": {"updated_at": now}
                    }
                )
            
            # Create TrialClubAccess object
            access_data = TrialClubAccess(
                club_id=str(club["_id"]),
                club_name=club.get("name", ""),
                club_name_based_id=club.get("name_based_id", ""),
                captain_name=club.get("captain_details", {}).get("full_name", "Unknown Captain"),
                join_date=now,
                access_expires_date=access_expires,
                is_access_active=True
            )
            
            logger.info(f"Created trial club access for user {user_id}, club {club.get('name_based_id')}")
            return True, None, access_data
            
        except Exception as e:
            logger.error(f"Error creating trial club access: {e}")
            return False, f"Error creating trial club access: {str(e)}", None
    
    async def _batch_update_operations(self, user_id: str, club_id: str, access_expires: datetime, session):
        """Batch all update operations - same logic as original but optimized"""
        try:
            # Update club member count and add detailed member info
            await self._update_club_member_count(club_id)
            
            # Add detailed member information to both clubs and users collections
            from .membership_service import add_member_to_club
            await add_member_to_club(
                user_id=user_id,
                club_id=club_id,
                pricing_plan="trial",
                is_trial=True,
                membership_status="trial",
                payment_id=None,
                amount_paid=0.0,
                end_date=access_expires
            )
            
            # Explicitly update club_count in auth database for members
            # This ensures club_count = 1 when member joins first club, and stays 1 forever
            await self._update_member_club_count(user_id)
            
        except Exception as e:
            logger.error(f"Error in batch update operations: {e}")
            raise
