"""
Moderator Details Service

This service handles fetching comprehensive moderator details including:
- Profile information (name, email, phone, status)
- Assigned clubs with captain details
- Submitted picks with outcomes and statistics
- Locker room moderation actions
- Win/loss statistics and performance metrics

The service provides a complete read-only view of moderator data for admin oversight.
"""

import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId
from .db import (
    clubs_collection, club_memberships_collection, users_collection,
    club_picks_collection, locker_room_logs_collection
)
from .models import (
    ModeratorDetailsResponse, ModeratorDetailsData, ModeratorProfile,
    AssignedClubDetails, AssignedByCaptain, PickSubmitted, LockerRoomAction,
    WinLossStats, ModeratorStatus, ModeratorRole, LockerRoomActionType
)

class AdminModeratorDetailsService:
    def __init__(self):
        self.clubs_collection = clubs_collection
        self.club_memberships_collection = club_memberships_collection
        self.users_collection = users_collection
        self.club_picks_collection = club_picks_collection
        self.locker_room_logs_collection = locker_room_logs_collection

    async def get_moderator_details(self, moderator_id: str) -> ModeratorDetailsResponse:
        """
        Get comprehensive moderator details by moderator ID
        
        Args:
            moderator_id: The unique identifier of the moderator
            
        Returns:
            ModeratorDetailsResponse with complete moderator information
        """
        start_time = time.time()
        
        try:
            print(f"DEBUG: Fetching details for moderator {moderator_id}")
            
            # Validate moderator_id format
            try:
                moderator_object_id = ObjectId(moderator_id)
            except:
                return ModeratorDetailsResponse(
                    success=False,
                    message="Invalid moderator ID format",
                    error_code="INVALID_ID",
                    last_updated=datetime.utcnow().strftime("%d %b %Y %H:%M")
                )
            
            # Get moderator profile
            moderator_doc = await self.users_collection.find_one({"_id": moderator_object_id})
            if not moderator_doc:
                return ModeratorDetailsResponse(
                    success=False,
                    message="Moderator not found",
                    error_code="NOT_FOUND",
                    last_updated=datetime.utcnow().strftime("%d %b %Y %H:%M")
                )
            
            # Check if user is actually a moderator
            is_moderator = await self._verify_moderator_role(moderator_id)
            if not is_moderator:
                return ModeratorDetailsResponse(
                    success=False,
                    message="User is not a moderator",
                    error_code="NOT_MODERATOR",
                    last_updated=datetime.utcnow().strftime("%d %b %Y %H:%M")
                )
            
            # Get all moderator data components
            profile = await self._get_moderator_profile(moderator_doc)
            assigned_clubs = await self._get_assigned_clubs(moderator_id)
            picks_submitted = await self._get_submitted_picks(moderator_id)
            locker_room_actions = await self._get_locker_room_actions(moderator_id)
            win_loss_stats = await self._calculate_win_loss_stats(moderator_id)
            
            # Create comprehensive data object
            moderator_data = ModeratorDetailsData(
                profile=profile,
                assigned_clubs=assigned_clubs,
                picks_submitted=picks_submitted,
                locker_room_actions=locker_room_actions,
                win_loss_stats=win_loss_stats
            )
            
            end_time = time.time()
            response_time = round((end_time - start_time) * 1000, 2)
            
            return ModeratorDetailsResponse(
                success=True,
                message=f"Moderator details retrieved successfully",
                data=moderator_data,
                response_time_ms=response_time,
                last_updated=datetime.utcnow().strftime("%d %b %Y %H:%M")
            )
            
        except Exception as e:
            print(f"Error in get_moderator_details: {e}")
            end_time = time.time()
            response_time = round((end_time - start_time) * 1000, 2)
            
            return ModeratorDetailsResponse(
                success=False,
                message=f"Failed to retrieve moderator details: {str(e)}",
                error_code="INTERNAL_ERROR",
                response_time_ms=response_time,
                last_updated=datetime.utcnow().strftime("%d %b %Y %H:%M")
            )

    async def _verify_moderator_role(self, moderator_id: str) -> bool:
        """Verify that the user has moderator roles in any club"""
        try:
            moderator_roles = ["moderator", "analyst", "editor"]
            membership_count = await self.club_memberships_collection.count_documents({
                "user_id": moderator_id,
                "role": {"$in": moderator_roles},
                "is_active": True
            })
            return membership_count > 0
        except Exception as e:
            print(f"Error verifying moderator role: {e}")
            return False

    async def _get_moderator_profile(self, moderator_doc: Dict[str, Any]) -> ModeratorProfile:
        """Extract and format moderator profile information"""
        try:
            # Determine status based on verification and activity
            is_active = moderator_doc.get("is_active", False) and moderator_doc.get("is_verified", False)
            status = ModeratorStatus.ACTIVE if is_active else ModeratorStatus.INACTIVE
            
            profile = ModeratorProfile(
                moderator_id=str(moderator_doc.get("_id")),
                full_name=moderator_doc.get("full_name", "Unknown"),
                email=moderator_doc.get("email", "Unknown"),
                phone=moderator_doc.get("phone"),
                avatar_url=moderator_doc.get("profile_picture"),
                created_at=self._format_date_only(moderator_doc.get("created_at")),
                status=status,
                last_login=self._format_datetime(moderator_doc.get("last_login"))
            )
            
            return profile
            
        except Exception as e:
            print(f"Error getting moderator profile: {e}")
            return ModeratorProfile(
                moderator_id=str(moderator_doc.get("_id", "unknown")),
                full_name="Unknown",
                email="Unknown",
                created_at="Unknown",
                status=ModeratorStatus.INACTIVE
            )

    async def _get_assigned_clubs(self, moderator_id: str) -> List[AssignedClubDetails]:
        """Get all clubs where the moderator is assigned with captain details"""
        try:
            assigned_clubs = []
            
            # Get all club memberships for the moderator
            memberships_cursor = self.club_memberships_collection.find({
                "user_id": moderator_id,
                "role": {"$in": ["moderator", "analyst", "editor"]},
                "is_active": True
            })
            
            async for membership in memberships_cursor:
                club_id = membership.get("club_id")
                if not club_id:
                    continue
                
                # Get club details
                club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                if not club_doc or club_doc.get("is_deleted"):
                    continue
                
                # Get captain details
                captain_id = club_doc.get("captain_id")
                captain_name = "Unknown Captain"
                captain_email = None
                
                if captain_id:
                    captain_doc = await self.users_collection.find_one({"_id": ObjectId(captain_id)})
                    if captain_doc:
                        captain_name = captain_doc.get("full_name", "Unknown Captain")
                        captain_email = captain_doc.get("email")
                
                assigned_by = AssignedByCaptain(
                    captain_id=captain_id or "unknown",
                    captain_name=captain_name,
                    captain_email=captain_email
                )
                
                # Determine role
                role = ModeratorRole(membership.get("role", "moderator"))
                
                # Create assigned club details
                club_details = AssignedClubDetails(
                    club_id=club_id,
                    club_name=club_doc.get("name", "Unknown Club"),
                    role=role,
                    assigned_by=assigned_by,
                    assigned_date=self._format_datetime(membership.get("joined_date")),
                    status="active" if membership.get("is_active") else "inactive",
                    subscription_status=membership.get("subscription_status", "unknown")
                )
                
                assigned_clubs.append(club_details)
            
            return assigned_clubs
            
        except Exception as e:
            print(f"Error getting assigned clubs: {e}")
            return []

    async def _get_submitted_picks(self, moderator_id: str) -> List[PickSubmitted]:
        """Get all picks submitted by the moderator"""
        try:
            submitted_picks = []
            
            # Get all picks submitted by the moderator
            picks_cursor = self.club_picks_collection.find({
                "submitted_by_id": moderator_id
            }).sort("date_submitted", -1)  # Most recent first
            
            async for pick_doc in picks_cursor:
                # Get club name for context
                club_id = pick_doc.get("club_id")
                club_name = "Unknown Club"
                
                if club_id:
                    club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                    if club_doc:
                        club_name = club_doc.get("name", "Unknown Club")
                
                # Determine outcome string
                status = pick_doc.get("status", "pending")
                outcome_map = {
                    "won": "Win",
                    "lost": "Loss", 
                    "pending": "Pending",
                    "cancelled": "Cancelled",
                    "void": "Void"
                }
                outcome = outcome_map.get(status, "Pending")
                
                # Check if pick is tagged (has tags)
                tags = pick_doc.get("tags", [])
                tagged_pick = len(tags) > 0
                
                pick = PickSubmitted(
                    pick_id=str(pick_doc.get("_id")),
                    game_name=pick_doc.get("game_name", pick_doc.get("title", "Unknown Game")),
                    title=pick_doc.get("title", "Untitled Pick"),
                    description=pick_doc.get("description"),
                    pick_type=pick_doc.get("pick_type", "single"),
                    sport=pick_doc.get("sport"),
                    odds=pick_doc.get("odds"),
                    stake=pick_doc.get("stake"),
                    submission_date=self._format_datetime(pick_doc.get("date_submitted")),
                    game_date=self._format_datetime(pick_doc.get("game_date")),
                    outcome=outcome,
                    outcome_date=self._format_datetime(pick_doc.get("outcome_date")),
                    profit_loss=pick_doc.get("profit_loss"),
                    tagged_pick=tagged_pick,
                    confidence_level=pick_doc.get("confidence_level"),
                    club_name=club_name
                )
                
                submitted_picks.append(pick)
            
            return submitted_picks
            
        except Exception as e:
            print(f"Error getting submitted picks: {e}")
            return []

    async def _get_locker_room_actions(self, moderator_id: str) -> List[LockerRoomAction]:
        """Get all locker room moderation actions performed by the moderator"""
        try:
            locker_room_actions = []
            
            # Get all moderation actions performed by the moderator
            actions_cursor = self.locker_room_logs_collection.find({
                "moderator_id": moderator_id
            }).sort("action_date", -1)  # Most recent first
            
            async for action_doc in actions_cursor:
                # Get club name for context
                club_id = action_doc.get("club_id")
                club_name = "Unknown Club"
                
                if club_id:
                    club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
                    if club_doc:
                        club_name = club_doc.get("name", "Unknown Club")
                
                # Map action type to enum (with fallback)
                action_type_str = action_doc.get("action_type", "Unknown Action")
                try:
                    action_type = LockerRoomActionType(action_type_str)
                except ValueError:
                    # If action type doesn't match enum, create a generic one
                    action_type = LockerRoomActionType.DELETE_POST  # Default fallback
                
                action = LockerRoomAction(
                    action_id=str(action_doc.get("_id")),
                    action_type=action_type,
                    club_name=club_name,
                    club_id=club_id or "unknown",
                    target_user=action_doc.get("target_user"),
                    action_date=self._format_datetime(action_doc.get("action_date")),
                    reason=action_doc.get("reason"),
                    duration=action_doc.get("duration"),
                    details=action_doc.get("details")
                )
                
                locker_room_actions.append(action)
            
            return locker_room_actions
            
        except Exception as e:
            print(f"Error getting locker room actions: {e}")
            return []

    async def _calculate_win_loss_stats(self, moderator_id: str) -> WinLossStats:
        """Calculate comprehensive win/loss statistics for the moderator"""
        try:
            # Get all picks for calculation
            picks_cursor = self.club_picks_collection.find({"submitted_by_id": moderator_id})
            
            total_picks = 0
            win_count = 0
            loss_count = 0
            pending_count = 0
            cancelled_count = 0
            void_count = 0
            total_profit_loss = 0.0
            total_stakes = 0.0
            odds_sum = 0.0
            odds_count = 0
            
            # For streak calculation
            current_streak = 0
            best_streak = 0
            temp_streak = 0
            last_outcome = None
            
            picks_list = []
            async for pick in picks_cursor:
                picks_list.append(pick)
            
            # Sort by date for proper streak calculation
            picks_list.sort(key=lambda x: x.get("date_submitted", datetime.min))
            
            for pick in picks_list:
                total_picks += 1
                status = pick.get("status", "pending")
                profit_loss = pick.get("profit_loss", 0.0)
                stake = pick.get("stake", 0.0)
                odds = pick.get("odds")
                
                # Count by status
                if status == "won":
                    win_count += 1
                    total_profit_loss += profit_loss
                elif status == "lost":
                    loss_count += 1
                    total_profit_loss += profit_loss  # This should be negative
                elif status == "pending":
                    pending_count += 1
                elif status == "cancelled":
                    cancelled_count += 1
                elif status == "void":
                    void_count += 1
                
                # Accumulate stakes and odds
                total_stakes += stake
                if odds:
                    odds_sum += odds
                    odds_count += 1
                
                # Calculate streaks (only for completed picks)
                if status in ["won", "lost"]:
                    if status == "won":
                        if last_outcome == "won":
                            temp_streak += 1
                        else:
                            temp_streak = 1
                        current_streak = temp_streak
                        best_streak = max(best_streak, temp_streak)
                    else:  # lost
                        temp_streak = 0
                        current_streak = 0
                    
                    last_outcome = status
            
            # Calculate rates
            completed_picks = win_count + loss_count
            win_rate = (win_count / completed_picks * 100) if completed_picks > 0 else 0.0
            loss_rate = (loss_count / completed_picks * 100) if completed_picks > 0 else 0.0
            
            # Calculate average odds
            avg_odds = (odds_sum / odds_count) if odds_count > 0 else None
            
            # Calculate ROI (Return on Investment)
            roi = (total_profit_loss / total_stakes * 100) if total_stakes > 0 else 0.0
            
            return WinLossStats(
                total_picks=total_picks,
                win_count=win_count,
                loss_count=loss_count,
                pending_count=pending_count,
                cancelled_count=cancelled_count,
                void_count=void_count,
                win_rate=round(win_rate, 2),
                loss_rate=round(loss_rate, 2),
                profit_loss=round(total_profit_loss, 2),
                avg_odds=round(avg_odds, 2) if avg_odds else None,
                best_streak=best_streak,
                current_streak=current_streak,
                total_stakes=round(total_stakes, 2),
                roi=round(roi, 2)
            )
            
        except Exception as e:
            print(f"Error calculating win/loss stats: {e}")
            return WinLossStats(
                total_picks=0,
                win_count=0,
                loss_count=0,
                pending_count=0,
                cancelled_count=0,
                void_count=0,
                win_rate=0.0,
                loss_rate=0.0,
                profit_loss=0.0,
                best_streak=0,
                current_streak=0,
                total_stakes=0.0,
                roi=0.0
            )

    def _format_datetime(self, dt) -> Optional[str]:
        """Format datetime to DD MMM YYYY HH:mm format"""
        if not dt:
            return None
        
        try:
            if isinstance(dt, datetime):
                return dt.strftime("%d %b %Y %H:%M")
            return None
        except:
            return None

    def _format_date_only(self, dt) -> Optional[str]:
        """Format datetime to DD MMM YYYY format (date only)"""
        if not dt:
            return None
        
        try:
            if isinstance(dt, datetime):
                return dt.strftime("%d %b %Y")
            return None
        except:
            return None

# Global service instance
admin_moderator_details_service = AdminModeratorDetailsService()