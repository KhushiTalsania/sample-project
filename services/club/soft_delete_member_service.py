"""
Service for soft deleting members from clubs
"""

import logging
from typing import Dict, List, Optional, Tuple
from bson import ObjectId
from datetime import datetime

from .db import get_club_collection, get_user_collection
from .models import SoftDeleteMemberRequest, SoftDeleteMemberResponse
from .id_utils import is_valid_name_based_id

logger = logging.getLogger(__name__)

class SoftDeleteMemberService:
    """Service for soft deleting members from clubs"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
    
    async def soft_delete_member(self, request: SoftDeleteMemberRequest, captain_id: str) -> SoftDeleteMemberResponse:
        """
        Soft delete a member from a club (Captain only)
        
        Args:
            request: Soft delete member request
            captain_id: ID of the captain performing the action
            
        Returns:
            SoftDeleteMemberResponse: Result of the operation
        """
        try:
            logger.info(f"🗑️ Processing soft delete member request - club_id: {request.club_id}, member_user_id: {request.member_user_id}, captain_id: {captain_id}")
            
            # Validate club ownership
            club = await self._validate_club_ownership(request.club_id, captain_id)
            if not club:
                return SoftDeleteMemberResponse(
                    success=False,
                    message="Club not found or you don't have permission to delete members from this club",
                    club_id=request.club_id,
                    club_name="",
                    member_user_id=request.member_user_id,
                    member_name="",
                    membership_type="",
                    updated_arrays=[]
                )
            
            # Find the member in both arrays
            member_info = await self._find_member_in_club(club, request.member_user_id)
            if not member_info:
                return SoftDeleteMemberResponse(
                    success=False,
                    message="Member not found in this club",
                    club_id=request.club_id,
                    club_name=club.get("name", ""),
                    member_user_id=request.member_user_id,
                    member_name="",
                    membership_type="",
                    updated_arrays=[]
                )
            
            # Soft delete the member from both arrays
            updated_arrays = await self._soft_delete_member_from_arrays(club, request.member_user_id)
            
            if not updated_arrays:
                return SoftDeleteMemberResponse(
                    success=False,
                    message="Failed to soft delete member from club arrays",
                    club_id=request.club_id,
                    club_name=club.get("name", ""),
                    member_user_id=request.member_user_id,
                    member_name=member_info.get("full_name", ""),
                    membership_type=member_info.get("membership_type", ""),
                    updated_arrays=[]
                )
            
            # Update the user's clubs_joined array to set status and membership_status to inactive
            await self._update_user_clubs_joined(request.member_user_id, request.club_id)
            
            logger.info(f"✅ Member soft deleted successfully from club: {club.get('name')}")
            
            return SoftDeleteMemberResponse(
                success=True,
                message="Member soft deleted successfully",
                club_id=request.club_id,
                club_name=club.get("name", ""),
                member_user_id=request.member_user_id,
                member_name=member_info.get("full_name", ""),
                membership_type=member_info.get("membership_type", ""),
                updated_arrays=updated_arrays
            )
            
        except Exception as e:
            logger.error(f"❌ Error in soft delete member service: {e}")
            import traceback
            traceback.print_exc()
            return SoftDeleteMemberResponse(
                success=False,
                message=f"Internal server error: {str(e)}",
                club_id=request.club_id,
                club_name="",
                member_user_id=request.member_user_id,
                member_name="",
                membership_type="",
                updated_arrays=[]
            )
    
    async def _validate_club_ownership(self, club_id: str, captain_id: str) -> Optional[Dict]:
        """Validate that the captain owns the club"""
        try:
            logger.info(f"🔍 Validating club ownership - club_id: {club_id}, captain_id: {captain_id}")
            
            # First, try to find the club by name_based_id with captain_id filter
            # This is the most direct way to check ownership
            club = await self.club_collection.find_one({
                "name_based_id": club_id,
                "captain_id": captain_id
            })
            
            if club:
                logger.info(f"✅ Club found with captain ownership: {club.get('name')}")
                logger.info(f"   - Captain ID: {club.get('captain_id')}")
                logger.info(f"   - Is Active: {club.get('is_active')}")
                logger.info(f"   - Status: {club.get('status')}")
                return club
            
            # If not found with captain filter, check if club exists at all
            logger.info(f"🔍 Club not found with captain filter, checking if club exists...")
            
            if is_valid_name_based_id(club_id):
                club_exists = await self.club_collection.find_one({
                    "name_based_id": club_id
                })
            else:
                try:
                    club_exists = await self.club_collection.find_one({
                        "_id": ObjectId(club_id)
                    })
                except Exception:
                    logger.warning(f"❌ Invalid club ID format: {club_id}")
                    return None
            
            if not club_exists:
                logger.warning(f"❌ Club not found - club_id: {club_id}")
                
                # Debug: Show available clubs
                logger.info(f"🔍 Checking available clubs for debugging...")
                available_clubs = await self.club_collection.find({}).limit(10).to_list(length=10)
                
                logger.info(f"Available clubs ({len(available_clubs)}):")
                for club in available_clubs:
                    logger.info(f"  - {club.get('name')} (name_based_id: {club.get('name_based_id')}, captain_id: {club.get('captain_id')})")
                
                return None
            
            # Club exists but captain doesn't own it
            logger.warning(f"❌ Club found but captain doesn't own it")
            logger.info(f"   - Club: {club_exists.get('name')}")
            logger.info(f"   - Club Captain ID: {club_exists.get('captain_id')}")
            logger.info(f"   - Request Captain ID: {captain_id}")
            
            # Check if captain IDs match (in case of data type issues)
            stored_captain_id = str(club_exists.get('captain_id', ''))
            request_captain_id = str(captain_id)
            
            if stored_captain_id == request_captain_id:
                logger.info(f"✅ Captain IDs match after string conversion")
                return club_exists
            
            # Check what clubs this captain actually owns
            captain_clubs = await self.club_collection.find({
                "captain_id": captain_id
            }).to_list(length=5)
            
            logger.info(f"🔍 Captain {captain_id} owns {len(captain_clubs)} clubs:")
            for club in captain_clubs:
                logger.info(f"  - {club.get('name')} (ID: {club.get('name_based_id')})")
            
            return None
            
        except Exception as e:
            logger.error(f"Error validating club ownership: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _find_member_in_club(self, club: Dict, member_user_id: str) -> Optional[Dict]:
        """Find member information in the club's member arrays"""
        try:
            logger.info(f"🔍 Searching for member {member_user_id} in club arrays")
            
            # Check in paid_members array
            paid_members = club.get("paid_members", [])
            logger.info(f"🔍 Checking paid_members array with {len(paid_members)} members")
            for i, member in enumerate(paid_members):
                member_id = str(member.get("user_id"))
                logger.info(f"  - Member {i}: {member.get('full_name')} (ID: {member_id})")
                if member_id == str(member_user_id):
                    logger.info(f"✅ Found member in paid_members array: {member.get('full_name')}")
                    return member
            
            # Check in members array (trial members)
            members = club.get("members", [])
            logger.info(f"🔍 Checking members array with {len(members)} members")
            for i, member in enumerate(members):
                member_id = str(member.get("user_id"))
                logger.info(f"  - Member {i}: {member.get('full_name')} (ID: {member_id})")
                if member_id == str(member_user_id):
                    logger.info(f"✅ Found member in members array: {member.get('full_name')}")
                    return member
            
            # Try ObjectId comparison for both arrays
            try:
                member_object_id = ObjectId(member_user_id)
                logger.info(f"🔍 Trying ObjectId comparison with {member_object_id}")
                
                # Check paid_members with ObjectId
                for i, member in enumerate(paid_members):
                    member_id = member.get("user_id")
                    if isinstance(member_id, ObjectId) and member_id == member_object_id:
                        logger.info(f"✅ Found member in paid_members array (ObjectId): {member.get('full_name')}")
                        return member
                    elif isinstance(member_id, str):
                        try:
                            if ObjectId(member_id) == member_object_id:
                                logger.info(f"✅ Found member in paid_members array (ObjectId from string): {member.get('full_name')}")
                                return member
                        except:
                            pass
                
                # Check members with ObjectId
                for i, member in enumerate(members):
                    member_id = member.get("user_id")
                    if isinstance(member_id, ObjectId) and member_id == member_object_id:
                        logger.info(f"✅ Found member in members array (ObjectId): {member.get('full_name')}")
                        return member
                    elif isinstance(member_id, str):
                        try:
                            if ObjectId(member_id) == member_object_id:
                                logger.info(f"✅ Found member in members array (ObjectId from string): {member.get('full_name')}")
                                return member
                        except:
                            pass
            except Exception as e:
                logger.warning(f"⚠️ ObjectId comparison failed: {e}")
            
            logger.warning(f"❌ Member {member_user_id} not found in any club array")
            logger.info(f"🔍 Available member IDs in paid_members: {[str(m.get('user_id')) for m in paid_members]}")
            logger.info(f"🔍 Available member IDs in members: {[str(m.get('user_id')) for m in members]}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding member in club: {e}")
            return None
    
    async def _soft_delete_member_from_arrays(self, club: Dict, member_user_id: str) -> List[str]:
        """Soft delete member from both paid_members and members arrays"""
        try:
            logger.info(f"🗑️ Soft deleting member {member_user_id} from club arrays")
            
            club_id = club.get("_id")
            updated_arrays = []
            
            # Try string comparison first
            paid_members_result = await self.club_collection.update_one(
                {
                    "_id": club_id,
                    "paid_members.user_id": member_user_id
                },
                {
                    "$set": {
                        "paid_members.$.status": "inactive",
                        "paid_members.$.membership_status": "inactive",
                        "paid_members.$.updated_at": datetime.utcnow()
                    }
                }
            )
            
            if paid_members_result.modified_count > 0:
                updated_arrays.append("paid_members")
                logger.info(f"✅ Updated paid_members array for member {member_user_id} (string)")
            else:
                # Try ObjectId comparison for paid_members
                try:
                    member_object_id = ObjectId(member_user_id)
                    paid_members_result = await self.club_collection.update_one(
                        {
                            "_id": club_id,
                            "paid_members.user_id": member_object_id
                        },
                        {
                            "$set": {
                                "paid_members.$.status": "inactive",
                                "paid_members.$.membership_status": "inactive",
                                "paid_members.$.updated_at": datetime.utcnow()
                            }
                        }
                    )
                    
                    if paid_members_result.modified_count > 0:
                        updated_arrays.append("paid_members")
                        logger.info(f"✅ Updated paid_members array for member {member_user_id} (ObjectId)")
                except Exception as e:
                    logger.warning(f"⚠️ ObjectId comparison failed for paid_members: {e}")
            
            # Try string comparison first for members
            members_result = await self.club_collection.update_one(
                {
                    "_id": club_id,
                    "members.user_id": member_user_id
                },
                {
                    "$set": {
                        "members.$.status": "inactive",
                        "members.$.membership_status": "inactive",
                        "members.$.updated_at": datetime.utcnow()
                    }
                }
            )
            
            if members_result.modified_count > 0:
                updated_arrays.append("members")
                logger.info(f"✅ Updated members array for member {member_user_id} (string)")
            else:
                # Try ObjectId comparison for members
                try:
                    member_object_id = ObjectId(member_user_id)
                    members_result = await self.club_collection.update_one(
                        {
                            "_id": club_id,
                            "members.user_id": member_object_id
                        },
                        {
                            "$set": {
                                "members.$.status": "inactive",
                                "members.$.membership_status": "inactive",
                                "members.$.updated_at": datetime.utcnow()
                            }
                        }
                    )
                    
                    if members_result.modified_count > 0:
                        updated_arrays.append("members")
                        logger.info(f"✅ Updated members array for member {member_user_id} (ObjectId)")
                except Exception as e:
                    logger.warning(f"⚠️ ObjectId comparison failed for members: {e}")
            
            if not updated_arrays:
                logger.warning(f"❌ No arrays were updated for member {member_user_id}")
            
            return updated_arrays
            
        except Exception as e:
            logger.error(f"Error soft deleting member from arrays: {e}")
            return []
    
    async def _update_user_clubs_joined(self, member_user_id: str, club_id: str) -> None:
        """Update the user's clubs_joined array to set status and membership_status to inactive"""
        try:
            logger.info(f"🔄 Updating user's clubs_joined array - user_id: {member_user_id}, club_id: {club_id}")
            
            # Convert club_id to ObjectId if it's a string
            if isinstance(club_id, str):
                try:
                    club_object_id = ObjectId(club_id)
                except Exception:
                    # If it's not a valid ObjectId, it might be a name_based_id
                    # Find the club by name_based_id to get the ObjectId
                    club = await self.club_collection.find_one({"name_based_id": club_id})
                    if club:
                        club_object_id = club["_id"]
                    else:
                        logger.warning(f"❌ Club not found for club_id: {club_id}")
                        return
            else:
                club_object_id = club_id
            
            # Update the user's clubs_joined array
            result = await self.user_collection.update_one(
                {
                    "_id": ObjectId(member_user_id),
                    "clubs_joined.club_id": str(club_object_id)
                },
                {
                    "$set": {
                        "clubs_joined.$.status": "inactive",
                        "clubs_joined.$.membership_status": "inactive",
                        "clubs_joined.$.is_active": False,
                        "clubs_joined.$.updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Successfully updated user's clubs_joined array for user: {member_user_id}")
            else:
                logger.warning(f"⚠️ No user document was updated for user: {member_user_id}")
                
        except Exception as e:
            logger.error(f"❌ Error updating user's clubs_joined array: {e}")
            import traceback
            traceback.print_exc()

# Service instance
_soft_delete_member_service = None

def get_soft_delete_member_service() -> SoftDeleteMemberService:
    """Get the soft delete member service instance"""
    global _soft_delete_member_service
    if _soft_delete_member_service is None:
        _soft_delete_member_service = SoftDeleteMemberService()
    return _soft_delete_member_service
