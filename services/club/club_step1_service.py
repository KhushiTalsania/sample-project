from typing import Optional
from datetime import datetime, timezone
from bson import ObjectId
from .db import get_club_collection, get_user_collection
from .models import ClubStep1CreateRequest, ClubStep1Response, ClubStep1Document, ClubStatus
from .id_utils import generate_name_based_id

import logging

logger = logging.getLogger(__name__)

async def verify_captain_eligibility(captain_id: str) -> bool:
    """Verify if captain is eligible to create clubs"""
    try:
        user_collection = get_user_collection()
        captain_object_id = ObjectId(captain_id)
        
        captain = await user_collection.find_one({"_id": captain_object_id})
        
        if not captain:
            logger.warning(f"Captain not found: {captain_id}")
            return False
        
        # Check if user is a captain
        if captain.get("role") != "Captain":
            logger.warning(f"User is not a captain: {captain_id}, role: {captain.get('role')}")
            return False
        
        # Check membership status
        membership_status = captain.get("membership_status", "none")
        membership_type = captain.get("membership_type", "none")
        
        # Captain must have active membership and be either paid or trial
        if membership_status != "active":
            logger.warning(f"Captain membership not active: {captain_id}, status: {membership_status}")
            return False
        
        if membership_type not in ["paid", "trial"]:
            logger.warning(f"Captain membership type not eligible: {captain_id}, type: {membership_type}")
            return False
        
        logger.info(f"Captain {captain_id} is eligible to create clubs")
        return True
        
    except Exception as e:
        logger.error(f"Error verifying captain eligibility: {e}")
        return False

async def create_club_step1(club_data: ClubStep1CreateRequest, captain_id: str) -> Optional[dict]:
    """Create club step 1 document"""
    try:
        club_collection = get_club_collection()
        user_collection = get_user_collection()
        
        # Create timestamps
        now = datetime.now(timezone.utc)
        
        # Generate name_based_id from club name
        name_based_id = generate_name_based_id(club_data.name)
        
        # Fetch captain details
        captain_object_id = ObjectId(captain_id)
        captain = await user_collection.find_one({"_id": captain_object_id})
        
        if not captain:
            logger.error(f"Captain not found: {captain_id}")
            return None
        
        # Generate captain name_based_id
        captain_name_based_id = generate_name_based_id(captain.get("full_name", ""))
        
        # Prepare captain details
        captain_details = {
            "id": captain_id,
            "full_name": captain.get("full_name", ""),
            "name_based_id": captain_name_based_id
        }
        
        # Create club document
        club_doc = ClubStep1Document(
            name=club_data.name,
            name_based_id=name_based_id,
            description=club_data.description,
            sub_description=club_data.sub_description,
            logo_url=club_data.logo_url,
            banner_url=club_data.banner_url,
            status=ClubStatus.PENDING,
            club_complete_step=1,
            captain_id=captain_id,
            captain_details=captain_details,
            created_at=now,
            updated_at=now
        )
        
        # Convert to dict for MongoDB insertion
        club_dict = club_doc.model_dump()
        
        # Double-check uniqueness right before insertion (defense in depth)
        logger.info(f"Double-checking uniqueness before database insertion for name: '{club_data.name}'")
        final_check = await club_collection.find_one({
            "name": {"$regex": f"^{club_data.name}$", "$options": "i"},
            "$or": [
                {"is_deleted": {"$ne": True}},
                {"is_deleted": {"$exists": False}}
            ]
        })
        
        if final_check:
            logger.error(f"Uniqueness violation detected right before insertion for name: '{club_data.name}'")
            raise ValueError(f"Club name '{club_data.name}' already exists")
        
        # Insert into database
        logger.info(f"Inserting club document into database for name: '{club_data.name}'")
        try:
            result = await club_collection.insert_one(club_dict)
            
            if not result.inserted_id:
                logger.error("Failed to insert club document")
                return None
                
        except Exception as insert_error:
            logger.error(f"Database insertion error for club '{club_data.name}': {insert_error}")
            
            # Check if it's a duplicate key error
            if "duplicate key error" in str(insert_error).lower() or "e11000" in str(insert_error):
                logger.error(f"Duplicate key error during insertion for club '{club_data.name}'")
                raise ValueError(f"Club name '{club_data.name}' already exists")
            else:
                # Re-raise other database errors
                raise insert_error
        
        # Get the created club
        created_club = await club_collection.find_one({"_id": result.inserted_id})
        
        if not created_club:
            logger.error("Failed to retrieve created club")
            return None
        
        # Convert to dictionary for response with proper datetime handling
        club_response = {
            "id": str(created_club["_id"]),
            "name": created_club["name"],
            "name_based_id": created_club["name_based_id"],
            "description": created_club["description"],
            "sub_description": created_club.get("sub_description"),
            "logo_url": created_club.get("logo_url"),
            "status": created_club["status"],
            "club_complete_step": created_club["club_complete_step"],
            "captain_id": created_club["captain_id"],
            "captain": created_club.get("captain_details", {}),
            "created_at": created_club["created_at"],
            "updated_at": created_club["updated_at"]
        }
        
        logger.info(f"Club step 1 created successfully: {result.inserted_id}")
        return club_response
        
    except Exception as e:
        logger.error(f"Error creating club step 1: {e}")
        return None

async def get_club_step1_by_id(club_id: str) -> Optional[dict]:
    """Get club step 1 by ID"""
    try:
        club_collection = get_club_collection()
        club_object_id = ObjectId(club_id)
        
        club = await club_collection.find_one({"_id": club_object_id})
        
        if not club:
            return None
        
        # Convert to dictionary for response
        club_response = {
            "id": str(club["_id"]),
            "name": club["name"],
            "name_based_id": club.get("name_based_id", ""),
            "description": club["description"],
            "sub_description": club.get("sub_description"),
            "logo_url": club.get("logo_url"),
            "banner_url": club.get("banner_url"),
            "status": club["status"],
            "club_complete_step": club["club_complete_step"],
            "captain_id": club["captain_id"],
            "captain": club.get("captain_details", {}),
            "created_at": club["created_at"],
            "updated_at": club["updated_at"]
        }
        
        return club_response
        
    except Exception as e:
        logger.error(f"Error getting club step 1: {e}")
        return None

async def update_club_step1(club_id: str, club_data: ClubStep1CreateRequest) -> Optional[dict]:
    """Update club step 1"""
    try:
        club_collection = get_club_collection()
        club_object_id = ObjectId(club_id)
        
        # Generate new name_based_id if name changed
        name_based_id = generate_name_based_id(club_data.name)
        
        # Prepare update data
        update_data = {
            "name": club_data.name,
            "name_based_id": name_based_id,
            "description": club_data.description,
            "sub_description": club_data.sub_description,
            "logo_url": club_data.logo_url,
            "banner_url": club_data.banner_url,
            "updated_at": datetime.now(timezone.utc)
        }
        
        # Update in database
        result = await club_collection.update_one(
            {"_id": club_object_id},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            logger.warning(f"No changes made to club: {club_id}")
            return None
        
        # Get the updated club
        updated_club = await club_collection.find_one({"_id": club_object_id})
        
        if not updated_club:
            logger.error("Failed to retrieve updated club")
            return None
        
        # Convert to dictionary for response
        club_response = {
            "id": str(updated_club["_id"]),
            "name": updated_club["name"],
            "name_based_id": updated_club.get("name_based_id", ""),
            "description": updated_club["description"],
            "sub_description": updated_club.get("sub_description"),
            "logo_url": updated_club.get("logo_url"),
            "banner_url": updated_club.get("banner_url"),
            "status": updated_club["status"],
            "club_complete_step": updated_club["club_complete_step"],
            "captain_id": updated_club["captain_id"],
            "captain": updated_club.get("captain_details", {}),
            "created_at": updated_club["created_at"],
            "updated_at": updated_club["updated_at"]
        }
        
        logger.info(f"Club step 1 updated successfully: {club_id}")
        return club_response
        
    except Exception as e:
        logger.error(f"Error updating club step 1: {e}")
        return None
