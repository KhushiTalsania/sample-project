from typing import Optional, List, Tuple
from datetime import datetime, timezone
from bson import ObjectId
from .db import get_club_collection, get_user_collection, get_inclusions_collection, get_sports_collection
from .models import ClubStep2UpdateRequest, ClubStep2Response, ClubStep2Document, ClubStatus, ClubStep2UpdateSimpleRequest, ClubInclusionSelection, ClubSportSelection
from .auth import get_current_captain, verify_club_ownership
from .id_utils import is_valid_name_based_id
import logging
import os

logger = logging.getLogger(__name__)

class ClubStep2Service:
    """Service for managing club step 2 (what's included + top 3 sports)"""
    
    async def update_club_step2(self, club_id: str, step2_data: ClubStep2UpdateRequest, captain_id: str) -> Optional[dict]:
        """Update club with step 2 data (what's included + top 3 sports)"""
        try:
            club_collection = get_club_collection()
            
            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(club_id):
                # Search by name_based_id
                club = await club_collection.find_one({
                    "name_based_id": club_id,
                    "captain_id": captain_id
                })
                if not club:
                    logger.error(f"Club not found with name_based_id: {club_id}")
                    return None
                club_object_id = club["_id"]
            else:
                # Try to validate as ObjectId
                try:
                    club_object_id = ObjectId(club_id)
                except Exception:
                    logger.error(f"Invalid club ID format: {club_id}")
                    return None
                
                # Validate club exists and belongs to captain
                club = await club_collection.find_one({"_id": club_object_id})
                if not club:
                    logger.error(f"Club not found: {club_id}")
                    return None
            
            if club.get("captain_id") != captain_id:
                logger.error(f"Club {club_id} does not belong to captain {captain_id}")
                return None
            
            # Check if club is at step 1 or higher (can update step 2 data from step 1 onwards)
            current_step = club.get("club_complete_step", 0)
            if current_step < 1:
                logger.error(f"Club {club_id} is at step {current_step}, must be at least step 1 to update step 2 data")
                return None
            
            # Create update document
            now = datetime.now(timezone.utc)
            
            # Determine the club_complete_step to set
            # If club is at step 1, set to step 2. If already at step 2+, keep current step
            target_step = max(2, current_step)
            
            update_doc = {
                "whats_included": [inclusion.model_dump() for inclusion in step2_data.whats_included],
                "top_3_sports": [sport.model_dump() for sport in step2_data.top_3_sports],
                "club_complete_step": target_step,
                "updated_at": now
            }
            
            # Update club in database
            result = await club_collection.update_one(
                {"_id": club_object_id},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                # Retrieve the updated club
                updated_club = await club_collection.find_one({"_id": club_object_id})
                if updated_club:
                    # Convert ObjectId to string for API response
                    updated_club["id"] = str(updated_club.pop("_id"))
                    # Ensure name_based_id is included
                    if "name_based_id" not in updated_club:
                        updated_club["name_based_id"] = ""
                    return updated_club
                else:
                    logger.error(f"Failed to retrieve updated club: {club_id}")
                    return None
            else:
                logger.error(f"No changes made to club: {club_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error updating club step 2: {e}")
            return None
    
    async def update_club_step2_simple(self, club_id: str, step2_data: ClubStep2UpdateSimpleRequest, captain_id: str) -> Optional[dict]:
        """Update club with step 2 data using simplified request (only titles and names)"""
        try:
            club_collection = get_club_collection()
            inclusions_collection = get_inclusions_collection()
            sports_collection = get_sports_collection()
            
            logger.info(f"Starting update_club_step2_simple for club_id: {club_id}, captain_id: {captain_id}")
            
            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(club_id):
                logger.info(f"Searching for club by name_based_id: {club_id}")
                # Search by name_based_id
                club = await club_collection.find_one({
                    "name_based_id": club_id
                })
                if not club:
                    logger.error(f"Club not found with name_based_id: {club_id}")
                    # Let's also check if there are any clubs with similar names for debugging
                    similar_clubs = await club_collection.find({"name_based_id": {"$regex": club_id, "$options": "i"}}).to_list(length=5)
                    if similar_clubs:
                        logger.info(f"Found similar clubs: {[c.get('name_based_id') for c in similar_clubs]}")
                    return None
                
                # Check ownership separately for better error messages
                if club.get("captain_id") != captain_id:
                    logger.error(f"Club {club_id} belongs to captain {club.get('captain_id')}, not {captain_id}")
                    return None
                    
                club_object_id = club["_id"]
                logger.info(f"Club found by name_based_id: {club_id}, ObjectId: {club_object_id}")
            else:
                logger.info(f"Searching for club by ObjectId: {club_id}")
                # Try to validate as ObjectId
                try:
                    club_object_id = ObjectId(club_id)
                except Exception:
                    logger.error(f"Invalid club ID format: {club_id}")
                    return None
                
                # Validate club exists
                club = await club_collection.find_one({"_id": club_object_id})
                if not club:
                    logger.error(f"Club not found with ObjectId: {club_id}")
                    return None
                
                # Check ownership
                if club.get("captain_id") != captain_id:
                    logger.error(f"Club {club_id} belongs to captain {club.get('captain_id')}, not {captain_id}")
                    return None
            
            logger.info(f"Club {club_id} found and ownership verified. Current step: {club.get('club_complete_step', 0)}")
            
            # Check if club is at step 1 or higher (can update step 2 data from step 1 onwards)
            current_step = club.get("club_complete_step", 0)
            if current_step < 1:
                logger.error(f"Club {club_id} is at step {current_step}, must be at least step 1 to update step 2 data")
                return None
            
            logger.info(f"Club {club_id} is at step {current_step}, proceeding with step 2 update")
            
            # Fetch complete inclusion data from admin database
            inclusion_titles = [inc.title for inc in step2_data.whats_included]
            logger.info(f"Fetching inclusions for titles: {inclusion_titles}")
            
            try:
                # First, let's check if we can connect to the admin database
                admin_db_name = os.getenv("ADMIN_DATABASE_NAME", "betting_main")
                logger.info(f"Connecting to admin database: {admin_db_name}")
                
                inclusions_data = await inclusions_collection.find({"title": {"$in": inclusion_titles}}).to_list(length=None)
                logger.info(f"Found {len(inclusions_data)} inclusions in admin database")
                
                # Log all available inclusions for debugging
                all_inclusions = await inclusions_collection.find({}).to_list(length=10)
                logger.info(f"Sample inclusions in admin database: {[inc.get('title') for inc in all_inclusions]}")
                
            except Exception as e:
                logger.error(f"Failed to fetch inclusions from admin database: {e}")
                logger.error(f"Admin database connection issue. Check ADMIN_DATABASE_NAME environment variable.")
                return None
            
            if len(inclusions_data) != len(inclusion_titles):
                found_titles = [inc["title"] for inc in inclusions_data]
                missing_titles = [title for title in inclusion_titles if title not in found_titles]
                logger.error(f"Some inclusions not found in admin database: {missing_titles}")
                logger.error(f"Found inclusions: {found_titles}")
                logger.error(f"Requested inclusions: {inclusion_titles}")
                logger.error(f"Available inclusions in admin database: {await inclusions_collection.count_documents({})}")
                return None
            
            # Fetch complete sports data from admin database
            sport_names = [sport.name for sport in step2_data.top_3_sports]
            logger.info(f"Fetching sports for names: {sport_names}")
            
            try:
                sports_data = await sports_collection.find({"name": {"$in": sport_names}}).to_list(length=None)
                logger.info(f"Found {len(sports_data)} sports in admin database")
                
                # Log all available sports for debugging
                all_sports = await sports_collection.find({}).to_list(length=10)
                logger.info(f"Sample sports in admin database: {[sport.get('name') for sport in all_sports]}")
                
            except Exception as e:
                logger.error(f"Failed to fetch sports from admin database: {e}")
                logger.error(f"Admin database connection issue. Check ADMIN_DATABASE_NAME environment variable.")
                return None
            
            if len(sports_data) != len(sport_names):
                found_names = [sport["name"] for sport in sports_data]
                missing_names = [name for name in sport_names if name not in found_names]
                logger.error(f"Some sports not found in admin database: {missing_names}")
                logger.error(f"Found sports: {found_names}")
                logger.error(f"Requested sports: {sport_names}")
                logger.error(f"Available sports in admin database: {await sports_collection.count_documents({})}")
                return None
            
            # Convert to ClubInclusionSelection and ClubSportSelection models
            whats_included = []
            for inc_data in inclusions_data:
                whats_included.append(ClubInclusionSelection(
                    title=inc_data["title"],
                    sub_desc=inc_data.get("sub_desc", ""),
                    logo_url=inc_data.get("logo_url")
                ))
            
            top_3_sports = []
            for sport_data in sports_data:
                top_3_sports.append(ClubSportSelection(
                    name=sport_data["name"],
                    icon=sport_data.get("icon", "")
                ))
            
            # Create update document
            now = datetime.now(timezone.utc)
            
            # Determine the club_complete_step to set
            # If club is at step 1, set to step 2. If already at step 2+, keep current step
            target_step = max(2, current_step)
            logger.info(f"Club {club_id} current step: {current_step}, target step: {target_step}")
            
            update_doc = {
                "whats_included": [inclusion.model_dump() for inclusion in whats_included],
                "top_3_sports": [sport.model_dump() for sport in top_3_sports],
                "club_complete_step": target_step,
                "updated_at": now
            }
            
            logger.info(f"Updating club {club_id} with step 2 data: {len(whats_included)} inclusions, {len(top_3_sports)} sports")
            
            # Update club in database
            result = await club_collection.update_one(
                {"_id": club_object_id},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                logger.info(f"Club {club_id} updated successfully")
                
                # Update club count for captain since step changed
                try:
                    from .db import update_club_count_on_step_change
                    await update_club_count_on_step_change(captain_id, club_id, target_step)
                    logger.info(f"✅ Club count updated for captain {captain_id} after step 2 completion")
                except Exception as count_error:
                    logger.warning(f"⚠️ Could not update club count for captain {captain_id}: {count_error}")
                
                # Retrieve the updated club
                updated_club = await club_collection.find_one({"_id": club_object_id})
                if updated_club:
                    # Convert ObjectId to string for API response
                    updated_club["id"] = str(updated_club.pop("_id"))
                    # Ensure name_based_id is included
                    if "name_based_id" not in updated_club:
                        updated_club["name_based_id"] = ""
                    logger.info(f"Club {club_id} step 2 update completed successfully")
                    return updated_club
                else:
                    logger.error(f"Failed to retrieve updated club: {club_id}")
                    return None
            else:
                logger.warning(f"No changes made to club: {club_id} - this might be normal if data is the same")
                # Even if no changes were made, return the current club data
                updated_club = await club_collection.find_one({"_id": club_object_id})
                if updated_club:
                    updated_club["id"] = str(updated_club.pop("_id"))
                    if "name_based_id" not in updated_club:
                        updated_club["name_based_id"] = ""
                    logger.info(f"Club {club_id} step 2 data unchanged, returning current data")
                    return updated_club
                else:
                    logger.error(f"Failed to retrieve club after update: {club_id}")
                    return None
                
        except Exception as e:
            logger.error(f"Error updating club step 2 simple: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    async def get_club_step2_data(self, club_id: str) -> Optional[dict]:
        """Get club step 2 data (what's included + top 3 sports)"""
        try:
            club_collection = get_club_collection()
            
            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(club_id):
                # Search by name_based_id
                club = await club_collection.find_one({"name_based_id": club_id})
                if not club:
                    return None
            else:
                # Try to validate as ObjectId
                try:
                    club_object_id = ObjectId(club_id)
                    club = await club_collection.find_one({"_id": club_object_id})
                    if not club:
                        return None
                except Exception:
                    return None
            
            # Return only step 2 related data
            step2_data = {
                "id": str(club["_id"]),
                "club_complete_step": club.get("club_complete_step", 0),
                "whats_included": club.get("whats_included", []),
                "top_3_sports": club.get("top_3_sports", []),
                "updated_at": club.get("updated_at")
            }
            
            return step2_data
            
        except Exception as e:
            logger.error(f"Error getting club step 2 data: {e}")
            return None
    
    async def validate_step2_data(self, step2_data: ClubStep2UpdateRequest) -> Tuple[bool, str]:
        """Validate step 2 data before updating"""
        try:
            # Validate inclusions
            if not step2_data.whats_included:
                return False, "At least one inclusion must be selected"
            
            if len(step2_data.whats_included) > 10:
                return False, "Maximum 10 inclusions allowed"
            
            # Validate sports
            if not step2_data.top_3_sports:
                return False, "At least one sport must be selected"
            
            if len(step2_data.top_3_sports) > 3:
                return False, "Maximum 3 sports allowed"
            
            # Validate unique selections
            inclusion_titles = [inc.title for inc in step2_data.whats_included]
            if len(inclusion_titles) != len(set(inclusion_titles)):
                return False, "Duplicate inclusions are not allowed"
            
            sport_names = [sport.name for sport in step2_data.top_3_sports]
            if len(sport_names) != len(set(sport_names)):
                return False, "Duplicate sports are not allowed"
            
            return True, "Validation successful"
            
        except Exception as e:
            logger.error(f"Error validating step 2 data: {e}")
            return False, f"Validation error: {str(e)}"

    async def validate_step2_simple_data(self, step2_data: ClubStep2UpdateSimpleRequest) -> Tuple[bool, str]:
        """Validate simplified step 2 data before updating"""
        try:
            # Validate inclusions
            if not step2_data.whats_included:
                return False, "At least one inclusion must be selected"
            
            if len(step2_data.whats_included) > 10:
                return False, "Maximum 10 inclusions allowed"
            
            # Validate sports
            if not step2_data.top_3_sports:
                return False, "At least one sport must be selected"
            
            if len(step2_data.top_3_sports) > 3:
                return False, "Maximum 3 sports allowed"
            
            # Validate unique selections
            inclusion_titles = [inc.title for inc in step2_data.whats_included]
            if len(inclusion_titles) != len(set(inclusion_titles)):
                return False, "Duplicate inclusions are not allowed"
            
            sport_names = [sport.name for sport in step2_data.top_3_sports]
            if len(sport_names) != len(set(sport_names)):
                return False, "Duplicate sports are not allowed"
            
            return True, "Validation successful"
            
        except Exception as e:
            logger.error(f"Error validating simplified step 2 data: {e}")
            return False, f"Validation error: {str(e)}"


