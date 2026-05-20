import logging
import re
import uuid
from typing import Optional, Tuple, List
from datetime import datetime, timezone
from bson import ObjectId
from .models import CreateHubRequest, HubDocument, HubResponse
from .db import HubDatabase, get_membership_collection, get_club_collection, get_trial_club_access_collection, get_user_collection, get_club_payments_collection
from .my_clubs_service import MyClubsService

logger = logging.getLogger(__name__)

class HubService:
    """Service class for hub operations"""
    
    def __init__(self, hub_db: HubDatabase):
        self.hub_db = hub_db
        self._indexes_created = False
        self.my_clubs_service = MyClubsService()
        
    def _generate_hub_name_based_id(self, title: str) -> str:
        """Generate a URL-friendly ID based on the hub title"""
        # Convert to lowercase and replace spaces with hyphens
        name_based_id = re.sub(r'[^a-zA-Z0-9\s-]', '', title.lower())
        name_based_id = re.sub(r'\s+', '-', name_based_id.strip())
        
        # Remove leading/trailing hyphens
        name_based_id = name_based_id.strip('-')
        
        # If empty after cleaning, generate a random ID
        if not name_based_id:
            name_based_id = f"hub-{uuid.uuid4().hex[:8]}"
        
        return name_based_id
        
    async def create_hub(self, request: CreateHubRequest, captain_id: str, captain_name: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Create a new hub entry
        
        Returns:
            Tuple[bool, Optional[str], Optional[str]]: (success, hub_id, error_message)
        """
        try:
            # Ensure indexes are created
            await self._ensure_indexes()
            
            logger.info(f"Creating hub entry for captain {captain_id} in club {request.club_id}")
            
            # Validate that the club exists and the user is the captain
            club_validation = await self._validate_club_and_captain(request.club_id, captain_id)
            if not club_validation[0]:
                return False, None, club_validation[1]
                
            club_doc = club_validation[2]
            
            # Generate hub_name_based_id from title
            hub_name_based_id = self._generate_hub_name_based_id(request.title)
            
            # Create hub document
            hub_data = HubDocument(
                title=request.title,
                description=request.description,
                resource_url=str(request.resource_url),
                platform=request.platform,
                club_id=club_doc["_id"],  # This is the ObjectId from database
                club_name_based_id=request.club_id,  # This is the name_based_id
                hub_name_based_id=hub_name_based_id,  # Generated from title
                captain_id=captain_id,
                captain_name=captain_name,
                created_at=datetime.now(timezone.utc),
                duration=request.duration,
                section=request.section,
                thumbnail=request.thumbnail,
                is_active=True
            )
            
            # Insert into database
            hub_id = await self.hub_db.insert_hub(hub_data)
            if not hub_id:
                error_msg = "Failed to create hub entry in database"
                logger.error(error_msg)
                return False, None, error_msg
                
            logger.info(f"Hub entry created successfully with ID: {hub_id}")
            return True, hub_id, None
            
        except Exception as e:
            error_msg = f"Error creating hub entry: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
            
    async def edit_hub(self, hub_id: str, request, captain_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Edit an existing hub entry
        
        Returns:
            Tuple[bool, Optional[str], Optional[str]]: (success, hub_id, error_message)
        """
        try:
            logger.info(f"Editing hub entry {hub_id} for captain {captain_id}")
            
            # Get the existing hub
            existing_hub = await self.hub_db.get_hub_by_id(hub_id)
            if not existing_hub:
                return False, None, "Hub entry not found"
                
            # Check if the user is the captain of this hub
            if existing_hub.captain_id != captain_id:
                return False, None, "Only the captain can edit this hub entry"
                
            # Prepare update data
            update_data = {}
            if request.title is not None:
                update_data["title"] = request.title
                # Don't change hub_name_based_id when editing to maintain URL stability
                # update_data["hub_name_based_id"] = self._generate_hub_name_based_id(request.title)
            if request.description is not None:
                update_data["description"] = request.description
            if request.resource_url is not None:
                update_data["resource_url"] = str(request.resource_url)
            if request.platform is not None:
                update_data["platform"] = request.platform
            if request.duration is not None:
                update_data["duration"] = request.duration
            if request.thumbnail is not None:
                update_data["thumbnail"] = request.thumbnail
            # Section is always required, so always include it
            update_data["section"] = request.section
                
            # Update the hub
            success = await self.hub_db.update_hub(hub_id, update_data)
            if not success:
                return False, None, "Failed to update hub entry"
                
            logger.info(f"Hub entry {hub_id} updated successfully")
            return True, hub_id, None
            
        except Exception as e:
            error_msg = f"Error editing hub entry: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
            
    async def delete_hub(self, hub_id: str, captain_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Delete a hub entry (soft delete)
        
        Returns:
            Tuple[bool, Optional[str], Optional[str]]: (success, hub_id, error_message)
        """
        try:
            logger.info(f"Deleting hub entry {hub_id} for captain {captain_id}")
            
            # Get the existing hub
            existing_hub = await self.hub_db.get_hub_by_id(hub_id)
            if not existing_hub:
                return False, None, "Hub entry not found"
                
            # Check if the user is the captain of this hub
            if existing_hub.captain_id != captain_id:
                return False, None, "Only the captain can delete this hub entry"
                
            # Soft delete the hub
            success = await self.hub_db.delete_hub(hub_id)
            if not success:
                return False, None, "Failed to delete hub entry"
                
            logger.info(f"Hub entry {hub_id} deleted successfully")
            return True, hub_id, None
            
        except Exception as e:
            error_msg = f"Error deleting hub entry: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
            
    async def _validate_club_and_captain(self, club_name_based_id: str, captain_id: str) -> Tuple[bool, Optional[str], Optional[dict]]:
        """
        Validate that the club exists and the user is the captain
        
        Returns:
            Tuple[bool, Optional[str], Optional[dict]]: (valid, error_message, club_document)
        """
        try:
            # Find club by name_based_id
            from .db import get_database
            database = await get_database()
            club_collection = database.clubs
            club_doc = await club_collection.find_one({"name_based_id": club_name_based_id})
            
            if not club_doc:
                error_msg = f"Club with name_based_id '{club_name_based_id}' not found"
                logger.warning(error_msg)
                return False, error_msg, None
                
            # Check if club is active
            if not club_doc.get("is_active", True):
                error_msg = f"Club '{club_name_based_id}' is not active"
                logger.warning(error_msg)
                return False, error_msg, None
                
            # Check if the user is the captain of this club
            if club_doc.get("captain_id") != captain_id:
                error_msg = f"User {captain_id} is not the captain of club '{club_name_based_id}'"
                logger.warning(error_msg)
                return False, error_msg, None
                
            logger.info(f"Club validation successful for {club_name_based_id}")
            return True, None, club_doc
            
        except Exception as e:
            error_msg = f"Error validating club and captain: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, None
            
    async def get_hub_by_id(self, hub_id: str) -> Optional[HubResponse]:
        """Get hub entry by ID and convert to response model"""
        try:
            hub_doc = await self.hub_db.get_hub_by_id(hub_id)
            if not hub_doc:
                return None
                
            # Convert to response model
            return HubResponse(
                hub_id=str(hub_doc.id),
                title=hub_doc.title,
                description=hub_doc.description,
                resource_url=hub_doc.resource_url,
                platform=hub_doc.platform,
                club_id=str(hub_doc.club_id) if hub_doc.club_id else "",
                club_name_based_id=hub_doc.club_name_based_id,
                hub_name_based_id=hub_doc.hub_name_based_id,
                captain_id=hub_doc.captain_id,
                captain_name=hub_doc.captain_name,
                created_at=hub_doc.created_at,
                duration=hub_doc.duration,
                section=hub_doc.section,
                thumbnail=hub_doc.thumbnail,
                is_active=hub_doc.is_active
            )
            
        except Exception as e:
            logger.error(f"Error getting hub by ID: {e}")
            return None
            
    async def get_hub_by_name_based_id(self, hub_name_based_id: str) -> Optional[HubResponse]:
        """Get hub entry by name_based_id and convert to response model"""
        try:
            hub_doc = await self.hub_db.get_hub_by_name_based_id(hub_name_based_id)
            if not hub_doc:
                return None
                
            # Convert to response model
            return HubResponse(
                hub_id=str(hub_doc.id),
                title=hub_doc.title,
                description=hub_doc.description,
                resource_url=hub_doc.resource_url,
                platform=hub_doc.platform,
                club_id=str(hub_doc.club_id) if hub_doc.club_id else "",
                club_name_based_id=hub_doc.club_name_based_id,
                hub_name_based_id=hub_doc.hub_name_based_id,
                captain_id=hub_doc.captain_id,
                captain_name=hub_doc.captain_name,
                created_at=hub_doc.created_at,
                duration=hub_doc.duration,
                section=hub_doc.section,
                thumbnail=hub_doc.thumbnail,
                is_active=hub_doc.is_active
            )
            
        except Exception as e:
            logger.error(f"Error getting hub by name_based_id: {e}")
            return None
            
    async def get_hubs_by_club(self, club_id: str, limit: int = 50) -> list:
        """Get all hub entries for a specific club"""
        try:
            hubs = await self.hub_db.get_hubs_by_club(club_id, limit)
            return [HubResponse(
                hub_id=str(hub.id),
                title=hub.title,
                description=hub.description,
                resource_url=hub.resource_url,
                platform=hub.platform,
                club_id=str(hub.club_id) if hub.club_id else "",
                club_name_based_id=hub.club_name_based_id,
                hub_name_based_id=hub.hub_name_based_id,
                captain_id=hub.captain_id,
                captain_name=hub.captain_name,
                created_at=hub.created_at,
                duration=hub.duration,
                section=hub.section,
                thumbnail=hub.thumbnail,
                is_active=hub.is_active
            ) for hub in hubs]
        except Exception as e:
            logger.error(f"Error getting hubs by club: {e}")
            return []
            
    async def get_hubs_by_captain(self, captain_id: str, limit: int = 50) -> list:
        """Get all hub entries created by a specific captain"""
        try:
            hubs = await self.hub_db.get_hubs_by_captain(captain_id, limit)
            return [HubResponse(
                hub_id=str(hub.id),
                title=hub.title,
                description=hub.description,
                resource_url=hub.resource_url,
                platform=hub.platform,
                club_id=str(hub.club_id) if hub.club_id else "",
                club_name_based_id=hub.club_name_based_id,
                hub_name_based_id=hub.hub_name_based_id,
                captain_id=hub.captain_id,
                captain_name=hub.captain_name,
                created_at=hub.created_at,
                duration=hub.duration,
                section=hub.section,
                thumbnail=hub.thumbnail,
                is_active=hub.is_active
            ) for hub in hubs]
        except Exception as e:
            logger.error(f"Error getting hubs by captain: {e}")
            return []
            
    async def _ensure_indexes(self):
        """Ensure hub database indexes are created"""
        if not self._indexes_created:
            try:
                await self.hub_db.create_hub_indexes()
                self._indexes_created = True
                logger.info("Hub database indexes created successfully")
            except Exception as e:
                logger.warning(f"Failed to create hub indexes: {e}")
                # Don't fail the operation if index creation fails

    async def get_filtered_hubs(
        self,
        search: Optional[str] = None,
        sort_by: str = "newest",
        club_name_based_id: Optional[str] = None,
        section: Optional[str] = None,
        user_id: str = None,
        user_role: str = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[bool, Optional[List[HubResponse]], Optional[str], Optional[dict]]:
        """
        Get filtered hubs with search, filtering, sorting, and pagination
        Supports both captains and members with proper access control
        
        Returns:
            Tuple[bool, Optional[List[HubResponse]], Optional[str], Optional[dict]]: 
            (success, hubs_list, error_message, pagination_info)
        """
        try:
            logger.info(f"Getting filtered hubs with filters: search={search}, sort_by={sort_by}, "
                       f"club={club_name_based_id}, section={section}, page={page}, page_size={page_size}")
            logger.info(f"User: {user_id}, Role: {user_role}")
            
            # Validate user_id and user_role are provided
            if not user_id or not user_role:
                logger.error("User ID and role are required but not provided")
                return False, None, "User ID and role are required", None
            
            # If club_name_based_id is provided, validate that the user has access to this club
            if club_name_based_id:
                logger.info(f"Validating club access for club: {club_name_based_id}")
                has_access, error_msg = await self.validate_club_access(user_id, user_role, club_name_based_id)
                if not has_access:
                    logger.error(f"Club access validation failed: {error_msg}")
                    return False, None, error_msg, None
                logger.info(f"Club access validation successful for: {club_name_based_id}")
            else:
                logger.info("No club filter provided, will show accessible hubs")
            
            # Get clubs that the user has access to
            success, accessible_clubs, error_msg = await self.get_user_accessible_clubs(user_id, user_role)
            if not success:
                logger.error(f"Failed to get accessible clubs: {error_msg}")
                return False, None, error_msg, None
            
            logger.info(f"User {user_id} accessible clubs: {accessible_clubs}")
            
            if not accessible_clubs:
                logger.info(f"User {user_id} has no accessible clubs")
                return True, [], None, {
                    "page": page,
                    "page_size": page_size,
                    "total_count": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_previous": False
                }
            
            # If a specific club is requested, filter to only that club
            if club_name_based_id:
                if club_name_based_id not in accessible_clubs:
                    logger.error(f"User {user_id} does not have access to club {club_name_based_id}")
                    return False, None, f"Access denied to club '{club_name_based_id}'", None
                accessible_clubs = [club_name_based_id]
            
            logger.info(f"User {user_id} has access to clubs: {accessible_clubs}")
            
            # Get hubs from accessible clubs
            hubs, total_count = await self.hub_db.get_filtered_hubs(
                search=search,
                club_name_based_id=None,  # We'll filter by accessible clubs
                section=section,
                captain_id=None,  # Don't filter by captain
                page=page,
                page_size=page_size,
                accessible_clubs=accessible_clubs  # Pass accessible clubs for filtering
            )
            
            logger.info(f"Database returned {len(hubs) if hubs else 0} hubs, total_count={total_count}")
            
            if not hubs:
                logger.info("No hubs found with the given filters")
                return True, [], None, {
                    "page": page,
                    "page_size": page_size,
                    "total_count": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_previous": False
                }
            
            # Convert to HubResponse objects
            hub_responses = []
            for hub in hubs:
                hub_response = HubResponse(
                    hub_id=str(hub.id),
                    title=hub.title,
                    description=hub.description,
                    resource_url=hub.resource_url,
                    platform=hub.platform,
                    club_id=str(hub.club_id) if hub.club_id else "",
                    club_name_based_id=hub.club_name_based_id,
                    hub_name_based_id=hub.hub_name_based_id,
                    captain_id=hub.captain_id,
                    captain_name=hub.captain_name,
                    created_at=hub.created_at,
                    duration=hub.duration,
                    section=hub.section,
                    thumbnail=hub.thumbnail,
                    is_active=hub.is_active
                )
                hub_responses.append(hub_response)
            
            # Apply sorting based on sort_by parameter
            if sort_by == "oldest":
                hub_responses.sort(key=lambda x: x.created_at)
            elif sort_by == "A-Z":
                hub_responses.sort(key=lambda x: x.title.lower())
            # "newest" is default (already sorted by created_at desc from database)
            
            # Calculate pagination info
            total_pages = (total_count + page_size - 1) // page_size
            has_next = page < total_pages
            has_previous = page > 1
            
            pagination_info = {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": has_next,
                "has_previous": has_previous
            }
            
            logger.info(f"Successfully retrieved {len(hub_responses)} hubs with pagination: {pagination_info}")
            return True, hub_responses, None, pagination_info
            
        except Exception as e:
            error_msg = f"Error getting filtered hubs: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg, None
            
    async def get_hub_statistics(self, club_name_based_id: Optional[str] = None, captain_id: str = None) -> Tuple[bool, Optional[dict], Optional[str]]:
        """
        Get hub statistics (counts by section type)
        
        Args:
            club_name_based_id: Optional club filter
            captain_id: Captain ID for validation
            
        Returns:
            Tuple[bool, Optional[dict], Optional[str]]: (success, stats_data, error_message)
        """
        try:
            logger.info(f"Getting hub statistics for club: {club_name_based_id or 'all captain clubs'}, captain: {captain_id}")
            
            # Validate captain_id is provided
            if not captain_id:
                logger.error("Captain ID is required but not provided")
                return False, None, "Captain ID is required"
            
            # If club_name_based_id is provided, validate that the captain owns this club
            if club_name_based_id:
                logger.info(f"Validating club ownership for club: {club_name_based_id}")
                club_validation = await self._validate_club_and_captain(club_name_based_id, captain_id)
                if not club_validation[0]:
                    logger.error(f"Club validation failed: {club_validation[1]}")
                    return False, None, club_validation[1]
                logger.info(f"Club validation successful for: {club_name_based_id}")
            else:
                # When no specific club is provided, get all clubs created by this captain
                logger.info(f"Getting all clubs created by captain: {captain_id}")
                captain_clubs = await self._get_captain_clubs(captain_id)
                if not captain_clubs:
                    logger.info(f"No clubs found for captain: {captain_id}")
                    # Return empty stats if captain has no clubs
                    stats = {
                        "total_strategy_videos": 0,
                        "total_training_videos": 0,
                        "total_partner_links": 0,
                        "total_content": 0,
                        "club_name_based_id": None
                    }
                    return True, stats, None
                
                # Get club name-based IDs for filtering
                club_name_based_ids = [club.get("name_based_id") for club in captain_clubs if club.get("name_based_id")]
                logger.info(f"Captain's clubs: {club_name_based_ids}")
                
                # Get statistics for all captain's clubs
                stats = await self.hub_db.get_hub_statistics_for_captain_clubs(club_name_based_ids)
                logger.info(f"Successfully retrieved hub statistics for all captain's clubs: {stats}")
                return True, stats, None
            
            # Get statistics from database for specific club
            stats = await self.hub_db.get_hub_statistics(club_name_based_id)
            
            logger.info(f"Successfully retrieved hub statistics: {stats}")
            return True, stats, None
            
        except Exception as e:
            error_msg = f"Error getting hub statistics: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg

    async def _get_captain_clubs(self, captain_id: str) -> List[dict]:
        """
        Get all clubs created by a captain
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            List[dict]: List of club documents
        """
        try:
            club_collection = get_club_collection()
            clubs = await club_collection.find({"captain_id": captain_id}).to_list(None)
            logger.info(f"Found {len(clubs)} clubs for captain: {captain_id}")
            return clubs
        except Exception as e:
            logger.error(f"Error getting captain clubs: {e}")
            return []

    async def get_user_accessible_clubs(self, user_id: str, user_role: str) -> Tuple[bool, Optional[List[str]], Optional[str]]:
        """
        Get clubs that a user can access hub content from
        
        For captains: Returns clubs they have created
        For members: Returns clubs they have joined
        
        Returns:
            Tuple[bool, Optional[List[str]], Optional[str]]: (success, club_name_based_ids, error_message)
        """
        try:
            logger.info(f"Getting accessible clubs for user: {user_id}, role: {user_role}")
            
            if user_role == "Captain":
                # For captains, get clubs they have created
                club_collection = get_club_collection()
                clubs = await club_collection.find({
                    "captain_id": user_id
                }).to_list(None)
                
                club_name_based_ids = [club["name_based_id"] for club in clubs if club.get("name_based_id")]
                logger.info(f"Captain {user_id} has access to {len(club_name_based_ids)} clubs: {club_name_based_ids}")
                
            else:
                # For members, get clubs they have joined (including trial access)
                membership_collection = get_membership_collection()
                memberships = await membership_collection.find({
                    "user_id": user_id,
                    "subscription_status": {"$in": ["active", "pending", "trial"]}
                }).to_list(None)
                
                # Also check for trial club access
                trial_access_collection = get_trial_club_access_collection()
                now = datetime.now(timezone.utc)
                trial_access = await trial_access_collection.find({
                    "user_id": user_id,
                    "is_access_active": True,
                    "access_expires_date": {"$gt": now}
                }).to_list(None)
                
                # Get club details for each membership
                club_collection = get_club_collection()
                club_name_based_ids = []
                
                for membership in memberships:
                    try:
                        club_object_id = ObjectId(membership["club_id"])
                        club = await club_collection.find_one({
                            "_id": club_object_id
                        })
                        
                        if club and club.get("name_based_id"):
                            club_name_based_ids.append(club["name_based_id"])
                    except Exception as e:
                        logger.warning(f"Error processing membership {membership.get('_id')}: {e}")
                        continue
                
                # Process trial access records
                for trial_access in trial_access:
                    try:
                        club_name_based_id = trial_access.get("club_name_based_id")
                        if club_name_based_id and club_name_based_id not in club_name_based_ids:
                            club_name_based_ids.append(club_name_based_id)
                    except Exception as e:
                        logger.warning(f"Error processing trial access {trial_access.get('_id')}: {e}")
                        continue
                
                # Also check club's member arrays directly (more reliable)
                logger.info(f"Checking club member arrays directly for user: {user_id}")
                now = datetime.now(timezone.utc)
                
                all_clubs = await club_collection.find({}).to_list(None)
                for club in all_clubs:
                    club_name_based_id = club.get("name_based_id")
                    if not club_name_based_id:
                        continue
                    
                    # Check if user is in members array (trial members)
                    members = club.get("members", [])
                    for member in members:
                        if member.get("user_id") == user_id:
                            # Check if membership is still valid
                            join_date = member.get("join_date")
                            end_date = member.get("end_date")
                            is_active = member.get("is_active", True)
                            membership_status = member.get("membership_status", "inactive")
                            
                            # Convert dates if needed
                            if isinstance(join_date, str):
                                join_date = datetime.fromisoformat(join_date.replace('Z', '+00:00'))
                            elif isinstance(join_date, datetime) and join_date.tzinfo is None:
                                join_date = join_date.replace(tzinfo=timezone.utc)
                                
                            if isinstance(end_date, str):
                                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                            elif isinstance(end_date, datetime) and end_date.tzinfo is None:
                                end_date = end_date.replace(tzinfo=timezone.utc)
                            
                            # Check if membership is valid
                            if (is_active and 
                                membership_status in ["active", "pending"] and
                                (not join_date or now >= join_date) and
                                (not end_date or now <= end_date)):
                                
                                if club_name_based_id not in club_name_based_ids:
                                    club_name_based_ids.append(club_name_based_id)
                                    logger.info(f"Found user {user_id} in trial members of club {club_name_based_id}")
                            break
                    
                    # Check if user is in paid_members array (paid members)
                    paid_members = club.get("paid_members", [])
                    for member in paid_members:
                        if member.get("user_id") == user_id:
                            # Check if membership is still valid
                            join_date = member.get("join_date")
                            end_date = member.get("end_date")
                            is_active = member.get("is_active", True)
                            membership_status = member.get("membership_status", "inactive")
                            
                            # Convert dates if needed
                            if isinstance(join_date, str):
                                join_date = datetime.fromisoformat(join_date.replace('Z', '+00:00'))
                            elif isinstance(join_date, datetime) and join_date.tzinfo is None:
                                join_date = join_date.replace(tzinfo=timezone.utc)
                                
                            if isinstance(end_date, str):
                                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                            elif isinstance(end_date, datetime) and end_date.tzinfo is None:
                                end_date = end_date.replace(tzinfo=timezone.utc)
                            
                            # Check if membership is valid
                            if (is_active and 
                                membership_status in ["active", "pending"] and
                                (not join_date or now >= join_date) and
                                (not end_date or now <= end_date)):
                                
                                if club_name_based_id not in club_name_based_ids:
                                    club_name_based_ids.append(club_name_based_id)
                                    logger.info(f"Found user {user_id} in paid members of club {club_name_based_id}")
                            break
                
                logger.info(f"Member {user_id} has access to {len(club_name_based_ids)} clubs: {club_name_based_ids}")
            
            return True, club_name_based_ids, None
            
        except Exception as e:
            error_msg = f"Error getting accessible clubs for user {user_id}: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg

    async def validate_club_access(self, user_id: str, user_role: str, club_name_based_id: str) -> Tuple[bool, Optional[str]]:
        """
        Validate if a user has access to a specific club's hub content
        
        Returns:
            Tuple[bool, Optional[str]]: (has_access, error_message)
        """
        try:
            logger.info(f"Validating club access for user: {user_id}, role: {user_role}, club: {club_name_based_id}")
            
            if user_role == "Captain":
                # For captains, check if they own the club
                club_collection = get_club_collection()
                
                # First, let's check if the club exists at all
                club_exists = await club_collection.find_one({"name_based_id": club_name_based_id})
                logger.info(f"Club exists check: {club_exists is not None}")
                if club_exists:
                    logger.info(f"Club found: captain_id={club_exists.get('captain_id')}, is_active={club_exists.get('is_active')}")
                
                # Now check with all conditions (let's be more lenient about is_active)
                club = await club_collection.find_one({
                    "name_based_id": club_name_based_id,
                    "captain_id": user_id
                })
                
                logger.info(f"Club with captain ownership check: {club is not None}")
                if not club:
                    # Let's get more detailed error information
                    club_by_name = await club_collection.find_one({"name_based_id": club_name_based_id})
                    if not club_by_name:
                        return False, f"Club '{club_name_based_id}' not found"
                    elif club_by_name.get("captain_id") != user_id:
                        return False, f"Captain does not own club '{club_name_based_id}' (owner: {club_by_name.get('captain_id')})"
                    elif not club_by_name.get("is_active", True):
                        return False, f"Club '{club_name_based_id}' is inactive"
                    else:
                        return False, f"Captain does not own club '{club_name_based_id}'"
                    
            else:
                # For members, check if they are a member of the club
                club_collection = get_club_collection()
                club = await club_collection.find_one({
                    "name_based_id": club_name_based_id
                })
                
                if not club:
                    return False, f"Club '{club_name_based_id}' not found"
                
                # Check if user is in club's members or paid_members arrays
                members = club.get("members", [])
                paid_members = club.get("paid_members", [])
                
                logger.info(f"Club '{club_name_based_id}' has {len(members)} trial members and {len(paid_members)} paid members")
                logger.info(f"Looking for user_id: {user_id}")
                logger.info(f"Trial members user_ids: {[m.get('user_id') for m in members]}")
                logger.info(f"Paid members user_ids: {[m.get('user_id') for m in paid_members]}")
                
                # Find user in members array (trial members)
                trial_member = None
                for member in members:
                    if member.get("user_id") == user_id:
                        trial_member = member
                        logger.info(f"Found trial member: {trial_member}")
                        break
                
                # Find user in paid_members array (paid members)
                paid_member = None
                for member in paid_members:
                    if member.get("user_id") == user_id:
                        paid_member = member
                        logger.info(f"Found paid member: {paid_member}")
                        break
                
                # Check if user is found in either array
                if not trial_member and not paid_member:
                    logger.error(f"User {user_id} not found in club '{club_name_based_id}' members or paid_members arrays")
                    return False, f"User is not a member of club '{club_name_based_id}'"
                
                # Check membership validity based on dates
                now = datetime.now(timezone.utc)
                
                member_info = trial_member or paid_member
                join_date = member_info.get("join_date")
                end_date = member_info.get("end_date")
                
                # Convert string dates to datetime if needed
                if isinstance(join_date, str):
                    join_date = datetime.fromisoformat(join_date.replace('Z', '+00:00'))
                elif isinstance(join_date, datetime) and join_date.tzinfo is None:
                    # Convert naive datetime to timezone-aware
                    join_date = join_date.replace(tzinfo=timezone.utc)
                
                if isinstance(end_date, str):
                    end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                elif isinstance(end_date, datetime) and end_date.tzinfo is None:
                    # Convert naive datetime to timezone-aware
                    end_date = end_date.replace(tzinfo=timezone.utc)
                
                # Check if membership is still valid
                if join_date and now < join_date:
                    return False, f"Membership for club '{club_name_based_id}' has not started yet"
                
                if end_date and now > end_date:
                    return False, f"Membership for club '{club_name_based_id}' has expired"
                
                # Check if member is active
                if not member_info.get("is_active", True):
                    return False, f"Membership for club '{club_name_based_id}' is inactive"
                
                # Check membership status
                membership_status = member_info.get("membership_status", "inactive")
                if membership_status not in ["active", "pending"]:
                    return False, f"Membership status for club '{club_name_based_id}' is {membership_status}"
            
            logger.info(f"Access validated successfully for user {user_id} to club {club_name_based_id}")
            return True, None
            
        except Exception as e:
            error_msg = f"Error validating club access: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    async def get_user_clubs(self, user_id: str, user_role: str) -> Tuple[bool, Optional[List[dict]], Optional[str]]:
        """
        Get clubs that a user has access to based on their role
        
        For captains: Returns clubs they have created
        For members: Returns clubs they have joined (from clubs_joined array in users collection)
        
        Returns:
            Tuple[bool, Optional[List[dict]], Optional[str]]: (success, clubs_list, error_message)
        """
        try:
            logger.info(f"Getting clubs for user: {user_id}, role: {user_role}")
            
            clubs_list = []
            
            if user_role == "Captain":
                # For captains, get clubs they have created
                club_collection = get_club_collection()
                clubs = await club_collection.find({
                    "captain_id": user_id,
                    "status": "approved"  # Only show approved clubs
                }).to_list(None)
                
                for club in clubs:
                    # Calculate member count - use total_members if available, otherwise calculate from member_count + paid_member_count
                    if club.get("total_members") is not None:
                        member_count = club.get("total_members", 0)
                    else:
                        member_count = club.get("member_count", 0) + club.get("paid_member_count", 0)
                    
                    club_info = {
                        "club_id": str(club["_id"]),
                        "name": club.get("name", ""),
                        "name_based_id": club.get("name_based_id", ""),
                        "description": club.get("description", ""),
                        "logo_url": club.get("logo_url"),
                        "member_count": member_count,  # This will be the value from total_members
                        "moderator_count": club.get("moderator_count", 0),
                        "is_active": club.get("is_active", True),
                        "created_at": club.get("created_at"),
                        "user_role": "captain"
                    }
                    clubs_list.append(club_info)
                
                logger.info(f"Captain {user_id} has {len(clubs_list)} clubs")
                
            else:
                # For members, get clubs from both clubs_joined array and moderator assignments
                user_collection = get_user_collection()
                user = await user_collection.find_one({"_id": ObjectId(user_id)})
                
                # Get club collection for fetching additional details
                club_collection = get_club_collection()
                
                # Track processed clubs to avoid duplicates
                processed_clubs = set()
                
                # First, get clubs from clubs_joined array
                if user and user.get("clubs_joined"):
                    clubs_joined = user["clubs_joined"]
                    logger.info(f"Found {len(clubs_joined)} clubs in user's clubs_joined array")
                    
                    for club_data in clubs_joined:
                        try:
                            # Check if the club is still active and the membership is active
                            if club_data.get("is_active", False):
                                club_id = club_data.get("club_id", "")
                                
                                # Get additional club details from club collection
                                club_details = None
                                if club_id:
                                    try:
                                        club_object_id = ObjectId(club_id)
                                        club_details = await club_collection.find_one({
                                            "_id": club_object_id,
                                            "status": "approved"  # Only show approved clubs
                                        })
                                    except Exception as e:
                                        logger.warning(f"Error fetching club details for {club_id}: {e}")
                                print(f"Club details for {club_id}: {club_details}")
                                print(f"Total members in club_details: {club_details.get('total_members') if club_details else 'No club_details'}")
                                print(f"Member count in club_details: {club_details.get('member_count') if club_details else 'No club_details'}")
                                print(f"Paid member count in club_details: {club_details.get('paid_member_count') if club_details else 'No club_details'}")
                                
                                # Only add club if it's approved
                                if club_details:
                                    # Mark this club as processed
                                    processed_clubs.add(club_id)
                                    
                                    # Calculate member count - use total_members if available, otherwise calculate from member_count + paid_member_count
                                    if club_details.get("total_members") is not None:
                                        member_count = club_details.get("total_members", 0)
                                        print(f"Using total_members: {member_count}")
                                    else:
                                        member_count = club_details.get("member_count", 0) + club_details.get("paid_member_count", 0)
                                        print(f"Calculated member count: {club_details.get('member_count', 0)} + {club_details.get('paid_member_count', 0)} = {member_count}")
                                    
                                    club_info = {
                                        "club_id": club_id,
                                        "name": club_data.get("club_name", ""),
                                        "name_based_id": club_data.get("club_name_based_id", ""),
                                        "description": club_details.get("description", "") if club_details else "",
                                        "logo_url": club_details.get("logo_url") if club_details else None,
                                        "member_count": member_count,  # This will be the value from total_members
                                        "moderator_count": club_details.get("moderator_count", 0) if club_details else 0,
                                        "is_active": club_data.get("is_active", True),
                                        "created_at": club_data.get("created_at"),
                                        "user_role": "member",
                                        "membership_type": club_data.get("membership_type", ""),
                                        "membership_status": club_data.get("membership_status", ""),
                                        "join_date": club_data.get("join_date"),
                                        "end_date": club_data.get("end_date")
                                    }
                                    clubs_list.append(club_info)
                        except Exception as e:
                            logger.warning(f"Error processing club data: {e}")
                            continue
                    
                    logger.info(f"Member {user_id} has {len(clubs_list)} active clubs from clubs_joined array")
                
                # Second, check for moderator assignments in clubs
                logger.info(f"Checking for moderator assignments for user {user_id}")
                moderator_clubs = await club_collection.find({
                    "detailed_moderators.user_id": user_id,
                    "status": "approved"
                }).to_list(None)
                
                logger.info(f"Found {len(moderator_clubs)} clubs where user {user_id} is a moderator")
                
                for club in moderator_clubs:
                    try:
                        club_id = str(club["_id"])
                        
                        # Skip if already processed as a member
                        if club_id in processed_clubs:
                            logger.info(f"Club {club_id} already processed as member, skipping moderator check")
                            continue
                        
                        # Find the moderator details
                        moderator_details = None
                        detailed_moderators = club.get("detailed_moderators", [])
                        for moderator in detailed_moderators:
                            if moderator.get("user_id") == user_id:
                                moderator_details = moderator
                                break
                        
                        if moderator_details:
                            # Calculate member count - use total_members if available, otherwise calculate from member_count + paid_member_count
                            if club.get("total_members") is not None:
                                member_count = club.get("total_members", 0)
                            else:
                                member_count = club.get("member_count", 0) + club.get("paid_member_count", 0)
                            
                            club_info = {
                                "club_id": club_id,
                                "name": club.get("name", ""),
                                "name_based_id": club.get("name_based_id", ""),
                                "description": club.get("description", ""),
                                "logo_url": club.get("logo_url"),
                                "member_count": member_count,
                                "moderator_count": club.get("moderator_count", 0),
                                "is_active": moderator_details.get("status", "active").lower() == "active",
                                "created_at": club.get("created_at"),
                                "user_role": "moderator",
                                "moderator_type": moderator_details.get("type_of_moderator", "free"),
                                "moderator_status": moderator_details.get("status", "active"),
                                "invited_at": moderator_details.get("invited_at"),
                                "responded_at": moderator_details.get("responded_at")
                            }
                            clubs_list.append(club_info)
                            logger.info(f"Added club {club.get('name')} as moderator assignment for user {user_id}")
                        
                    except Exception as e:
                        logger.warning(f"Error processing moderator club data: {e}")
                        continue
                
                # Fallback: Check membership collection for any missed memberships
                if not clubs_list:
                    logger.info(f"No clubs found from clubs_joined or moderator assignments, checking membership collection")
                    membership_collection = get_membership_collection()
                    memberships = await membership_collection.find({
                        "user_id": user_id,
                        "subscription_status": {"$in": ["active", "pending", "trial"]}
                    }).to_list(None)
                    
                    logger.info(f"Found {len(memberships)} memberships in membership collection")
                    
                    # Get club details for each membership
                    club_collection = get_club_collection()
                    
                    for membership in memberships:
                        try:
                            club_object_id = ObjectId(membership["club_id"])
                            club = await club_collection.find_one({
                                "_id": club_object_id,
                                "status": "approved"  # Only show approved clubs
                            })
                            
                            if club:
                                # Calculate member count - use total_members if available, otherwise calculate from member_count + paid_member_count
                                if club.get("total_members") is not None:
                                    member_count = club.get("total_members", 0)
                                else:
                                    member_count = club.get("member_count", 0) + club.get("paid_member_count", 0)
                                
                                club_info = {
                                    "club_id": str(club["_id"]),
                                    "name": club.get("name", ""),
                                    "name_based_id": club.get("name_based_id", ""),
                                    "description": club.get("description", ""),
                                    "logo_url": club.get("logo_url"),
                                    "member_count": member_count,  # This will be the value from total_members
                                    "moderator_count": club.get("moderator_count", 0),
                                    "is_active": club.get("is_active", True),
                                    "created_at": club.get("created_at"),
                                    "user_role": "member",
                                    "membership_type": "trial" if membership.get("is_trial_membership", False) else "paid",
                                    "membership_status": membership.get("subscription_status", ""),
                                    "join_date": membership.get("joined_date"),
                                    "end_date": membership.get("expires_date")
                                }
                                clubs_list.append(club_info)
                        except Exception as e:
                            logger.warning(f"Error processing membership {membership.get('_id')}: {e}")
                            continue
                    
                    logger.info(f"Member {user_id} has {len(clubs_list)} clubs from membership collection")
                
                logger.info(f"Total clubs found for user {user_id}: {len(clubs_list)} (from clubs_joined, moderator assignments, and membership collection)")
            
            return True, clubs_list, None
            
        except Exception as e:
            error_msg = f"Error getting user clubs: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg

    async def get_captain_club_statistics(self, captain_id: str, captain_name: str) -> Tuple[bool, Optional[dict], Optional[str]]:
        """
        Get comprehensive statistics for a captain's clubs
        
        Args:
            captain_id: Captain's user ID
            captain_name: Captain's full name
            
        Returns:
            Tuple[bool, Optional[dict], Optional[str]]: (success, stats_data, error_message)
        """
        try:
            logger.info(f"Getting club statistics for captain: {captain_id}")
            
            # Get statistics from database
            stats = await self.hub_db.get_captain_club_statistics(captain_id)
            
            # Add captain information
            stats["captain_id"] = captain_id
            stats["captain_name"] = captain_name
            stats["message"] = f"Successfully retrieved statistics for {captain_name}"
            
            logger.info(f"Successfully retrieved club statistics for captain: {captain_id}")
            return True, stats, None
            
        except Exception as e:
            error_msg = f"Error getting captain club statistics: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg

    async def get_member_club_detail(self, user_id: str, club_name_based_id: str) -> Tuple[bool, Optional[dict], Optional[str]]:
        """
        Get detailed information about a specific club for a member
        
        Args:
            user_id: Member's user ID
            club_name_based_id: Club's name-based ID
            
        Returns:
            Tuple[bool, Optional[dict], Optional[str]]: (success, club_detail_data, error_message)
        """
        try:
            logger.info(f"Getting club detail for member {user_id}, club {club_name_based_id}")
            
            # First, verify that the member has access to this club
            user_collection = get_user_collection()
            user = await user_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                return False, None, "User not found"
            
            # Check if user has joined this club
            clubs_joined = user.get("clubs_joined", [])
            logger.info(f"User {user_id} has {len(clubs_joined)} clubs joined: {[c.get('club_name_based_id') for c in clubs_joined]}")
            member_club_data = None
            
            for club_data in clubs_joined:
                if (club_data.get("club_name_based_id") == club_name_based_id and 
                    club_data.get("is_active", False)):
                    member_club_data = club_data
                    logger.info(f"Found member access for club {club_name_based_id}")
                    break
            
            if not member_club_data:
                # Fallback: Check membership collection and moderator access
                membership_collection = get_membership_collection()
                club_collection = get_club_collection()
                
                # Find the club first
                club = await club_collection.find_one({"name_based_id": club_name_based_id})
                if not club:
                    return False, None, "Club not found"
                
                logger.info(f"Found club {club_name_based_id}: {club.get('name', 'Unknown')}")
                logger.info(f"Club detailed_moderators: {club.get('detailed_moderators', [])}")
                
                # Check if user has membership
                membership = await membership_collection.find_one({
                    "user_id": user_id,
                    "club_id": str(club["_id"]),
                    "subscription_status": {"$in": ["active", "pending", "trial"]}
                })
                logger.info(f"Membership check for user {user_id} in club {club_name_based_id}: {membership is not None}")
                
                # Check if user is a moderator in this club
                detailed_moderators = club.get("detailed_moderators", [])
                logger.info(f"Checking moderator access for user {user_id} in club {club_name_based_id}")
                logger.info(f"Detailed moderators: {detailed_moderators}")
                
                is_moderator = False
                moderator_join_date = None
                
                for moderator in detailed_moderators:
                    moderator_user_id = moderator.get("user_id")
                    logger.info(f"Comparing user_id '{user_id}' with moderator user_id '{moderator_user_id}' (type: {type(moderator_user_id)})")
                    
                    # Convert both to strings for comparison
                    user_id_str = str(user_id).strip()
                    moderator_user_id_str = str(moderator_user_id).strip()
                    
                    logger.info(f"String comparison: '{user_id_str}' == '{moderator_user_id_str}' ? {user_id_str == moderator_user_id_str}")
                    
                    if user_id_str == moderator_user_id_str:
                        is_moderator = True
                        moderator_join_date = moderator.get("invited_at")
                        logger.info(f"Found moderator match! Join date: {moderator_join_date}")
                        break
                
                if not membership and not is_moderator:
                    # Check if user is a moderator in ANY club (for users who changed roles)
                    logger.info(f"User {user_id} not found as member or moderator of club {club_name_based_id}")
                    logger.info(f"Checking if user {user_id} is a moderator in any club...")
                    
                    # Search for clubs where this user is a moderator
                    all_clubs_with_moderator = await club_collection.find({
                        "detailed_moderators.user_id": user_id
                    }).to_list(None)
                    
                    if all_clubs_with_moderator:
                        logger.info(f"User {user_id} is a moderator in {len(all_clubs_with_moderator)} clubs: {[c.get('name_based_id') for c in all_clubs_with_moderator]}")
                        # User is a moderator in some clubs, but not this specific one
                        return False, None, f"You don't have access to this club. You are a moderator in other clubs: {', '.join([c.get('name_based_id') for c in all_clubs_with_moderator])}"
                    else:
                        logger.warning(f"User {user_id} is not a member or moderator of any club")
                        return False, None, "You don't have access to this club"
                
                # Create member club data based on access type
                if membership:
                    # Create member club data from membership
                    member_club_data = {
                        "club_id": str(club["_id"]),
                        "club_name": club.get("name", ""),
                        "club_name_based_id": club.get("name_based_id", ""),
                        "join_date": membership.get("joined_date"),
                        "end_date": membership.get("expires_date"),
                        "is_active": True
                    }
                elif is_moderator:
                    # Create member club data for moderator access
                    member_club_data = {
                        "club_id": str(club["_id"]),
                        "club_name": club.get("name", ""),
                        "club_name_based_id": club.get("name_based_id", ""),
                        "join_date": moderator_join_date,
                        "end_date": None,  # Moderators don't have end dates
                        "is_active": True
                    }
            
            # Get club details
            club_collection = get_club_collection()
            club = await club_collection.find_one({"name_based_id": club_name_based_id})
            
            if not club:
                return False, None, "Club not found"
            
            # Get hub content details (actual hub entries)
            hub_collection = self.hub_db.hub_collection
            hub_entries = await hub_collection.find({
                "club_name_based_id": club_name_based_id,
                "is_active": True
            }).to_list(None)
            
            # Categorize hub content
            strategy_videos = []
            training_videos = []
            partner_links = []
            
            for hub_entry in hub_entries:
                hub_item = {
                    "hub_id": str(hub_entry["_id"]),
                    "title": hub_entry.get("title", ""),
                    "description": hub_entry.get("description"),
                    "resource_url": hub_entry.get("resource_url", ""),
                    "platform": hub_entry.get("platform"),
                    "club_id": str(hub_entry.get("club_id", "")),
                    "club_name_based_id": hub_entry.get("club_name_based_id", ""),
                    "hub_name_based_id": hub_entry.get("hub_name_based_id", ""),
                    "captain_id": hub_entry.get("captain_id", ""),
                    "captain_name": hub_entry.get("captain_name", ""),
                    "created_at": hub_entry.get("created_at"),
                    "duration": hub_entry.get("duration"),
                    "section": hub_entry.get("section", ""),
                    "thumbnail": hub_entry.get("thumbnail"),
                    "is_active": hub_entry.get("is_active", True)
                }
                
                section = hub_entry.get("section", "").lower()
                if "strategy" in section:
                    strategy_videos.append(hub_item)
                elif "training" in section:
                    training_videos.append(hub_item)
                elif "partner" in section:
                    partner_links.append(hub_item)
            
            # Build moderator details
            moderator_details = []
            moderator_emails = club.get("moderator_emails", [])
            for email in moderator_emails:
                moderator_details.append({
                    "email": email,
                    "full_name": None  # We don't have full names in the current structure
                })
            
            # Build captain details
            captain_details = club.get("captain_details", {})
            captain_info = {
                "captain_id": club.get("captain_id", ""),
                "captain_name": captain_details.get("full_name", "Unknown Captain"),
                "captain_name_based_id": captain_details.get("name_based_id")
            }
            
            # Build hub content summary with actual entries
            hub_content = {
                "strategy_videos": strategy_videos,
                "training_videos": training_videos,
                "partner_links": partner_links,
                "strategy_videos_count": len(strategy_videos),
                "training_videos_count": len(training_videos),
                "partner_links_count": len(partner_links),
                "total_content": len(strategy_videos) + len(training_videos) + len(partner_links)
            }
            
            # Process top_3_sports to handle both string and object formats
            top_3_sports = club.get("top_3_sports", [])
            processed_sports = []
            for sport in top_3_sports:
                if isinstance(sport, dict):
                    # Handle object format: {"name": "Football", "icon": "string"}
                    processed_sports.append({
                        "name": sport.get("name", ""),
                        "icon": sport.get("icon")
                    })
                elif isinstance(sport, str):
                    # Handle string format: "Football"
                    processed_sports.append({
                        "name": sport,
                        "icon": None
                    })
            
            # Get trial club statistics from user data
            clubs_joined_count = user.get("clubs_joined_count", 0)
            clubs_remaining = user.get("clubs_remaining", 0)
            max_clubs = user.get("max_clubs", 4)
            
            # Get club rejection information
            rejection_type = club.get("rejection_type")
            rejection_reason = club.get("rejection_reason")
            rejected_by = club.get("rejected_by")
            is_resubmit = club.get("is_resubmit")
            is_club_reject_temporary = club.get("is_club_reject_temporary")
            is_club_reject_permanently = club.get("is_club_reject_permanently")
            
            # Determine user role in this club using centralized function
            user_role = await self.my_clubs_service._determine_user_role_in_club(user_id, str(club["_id"]))
            logger.info(f"User {user_id} has role '{user_role}' in club {club_name_based_id}")
            
            # Calculate real-time betting statistics
            club_id_str = str(club["_id"])
            captain_id = club.get("captain_id", "")
            betting_stats = await self._calculate_club_betting_stats(club_id_str, captain_id)
            logger.info(f"Calculated betting stats for club {club_name_based_id}: {betting_stats}")
            
            # Build response data
            club_detail = {
                "club_id": club_id_str,
                "logo_url": club.get("logo_url"),
                "club_name": club.get("name", ""),
                "name_based_id": club.get("name_based_id", ""),
                "created_at": club.get("created_at"),
                "status": club.get("status", "pending"),
                "description": club.get("description", ""),
                "sub_description": club.get("sub_description"),
                "member_join_date": member_club_data.get("join_date"),
                "member_end_date": member_club_data.get("end_date"),
                "moderator_details": moderator_details,
                "top_3_sports": processed_sports,
                "member_count": club.get("total_members", 0),
                # Real-time betting statistics
                "betting_stats": betting_stats,
                "total_bets": betting_stats["total_bets"],
                "win_pct": betting_stats["win_pct"],
                "loss_pct": betting_stats["loss_pct"],
                "captain_details": captain_info,
                "hub_content": hub_content,
                # Trial club statistics
                "clubs_joined_count": clubs_joined_count,
                "clubs_remaining": clubs_remaining,
                "max_clubs": max_clubs,
                # Club rejection information
                "rejection_type": rejection_type,
                "rejection_reason": rejection_reason,
                "rejected_by": rejected_by,
                "is_resubmit": is_resubmit,
                "is_club_reject_temporary": is_club_reject_temporary,
                "is_club_reject_permanently": is_club_reject_permanently,
                # User role
                "user_role": user_role
            }
            
            logger.info(f"Successfully retrieved club detail for member {user_id}, club {club_name_based_id}")
            return True, club_detail, None
            
        except Exception as e:
            error_msg = f"Error getting member club detail: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
    
    async def _has_club_access(self, user_id: str, club_id: str) -> bool:
        """Check if user has access to a club (member, moderator, or captain)"""
        try:
            user_role = await self.my_clubs_service._determine_user_role_in_club(user_id, club_id)
            return user_role in ["Captain", "Moderator", "Member"]
        except Exception as e:
            logger.error(f"Error checking club access for user {user_id}: {e}")
            return False

    async def get_captain_club_detail(self, captain_id: str, club_name_based_id: str) -> Tuple[bool, Optional[dict], Optional[str]]:
        """
        Get detailed information about a specific club for a captain
        
        Args:
            captain_id: Captain's user ID
            club_name_based_id: Club's name-based ID
            
        Returns:
            Tuple[bool, Optional[dict], Optional[str]]: (success, club_detail_data, error_message)
        """
        try:
            logger.info(f"Getting club detail for captain {captain_id}, club {club_name_based_id}")
            
            # Get club details
            club_collection = get_club_collection()
            club = await club_collection.find_one({"name_based_id": club_name_based_id})
            
            if not club:
                return False, None, "Club not found"
            
            # Determine user's role in the club using centralized function
            user_role = await self.my_clubs_service._determine_user_role_in_club(captain_id, str(club["_id"]))
            
            # If user has no role in this club, deny access
            if not user_role or user_role == "Member" and not await self._has_club_access(captain_id, str(club["_id"])):
                return False, None, "You don't have access to this club"
            
            logger.info(f"User {captain_id} has role '{user_role}' in club {club_name_based_id}")
            
            # Calculate betting statistics and revenue in parallel for better performance
            import asyncio
            
            # Run all calculations in parallel
            betting_stats_task = self._calculate_club_betting_stats(str(club["_id"]), club.get("captain_id"))
            revenue_task = self._calculate_club_revenue(club.get("captain_id"), str(club["_id"]))
            
            betting_stats, total_revenue = await asyncio.gather(
                betting_stats_task,
                revenue_task,
                return_exceptions=True
            )
            
            # Handle exceptions
            if isinstance(betting_stats, Exception):
                logger.error(f"Error calculating betting stats: {betting_stats}")
                betting_stats = {
                    "total_bets": 0,
                    "total_wins": 0,
                    "total_losses": 0,
                    "win_pct": 0.0,
                    "loss_pct": 0.0,
                    "total_spread": 0,
                    "total_over_under": 0,
                    "total_moneyline": 0,
                    "total_parlay": 0,
                    "pick_types": [],
                    "pick_type_counts": {}
                }
            
            if isinstance(total_revenue, Exception):
                logger.error(f"Error calculating revenue: {total_revenue}")
                total_revenue = 0.0
            
            # Process top_3_sports to handle both string and object formats
            top_3_sports = club.get("top_3_sports", [])
            processed_sports = []
            for sport in top_3_sports:
                if isinstance(sport, dict):
                    # Handle object format: {"name": "Football", "icon": "string"}
                    processed_sports.append({
                        "name": sport.get("name", ""),
                        "icon": sport.get("icon")
                    })
                elif isinstance(sport, str):
                    # Handle string format: "Football"
                    processed_sports.append({
                        "name": sport,
                        "icon": None
                    })
            
            # Build captain details
            captain_details = club.get("captain_details", {})
            
            # Extract betting statistics from calculated data
            total_bets = betting_stats.get("total_bets", 0)
            total_wins = betting_stats.get("total_wins", 0)
            total_losses = betting_stats.get("total_losses", 0)
            win_pct = betting_stats.get("win_pct", 0.0)
            loss_pct = betting_stats.get("loss_pct", 0.0)
            total_spread = betting_stats.get("total_spread", 0)
            total_over_under = betting_stats.get("total_over_under", 0)
            total_moneyline = betting_stats.get("total_moneyline", 0)
            total_parlay = betting_stats.get("total_parlay", 0)
            pick_types = betting_stats.get("pick_types", [])
            pick_type_counts = betting_stats.get("pick_type_counts", {})
            
            # Process whats_included to handle both string and object formats
            whats_included = club.get("whats_included", [])
            processed_whats_included = []
            for item in whats_included:
                if isinstance(item, dict):
                    # Handle object format: {"title": "Live Chat", "sub_desc": "...", "logo_url": "..."}
                    processed_whats_included.append({
                        "title": item.get("title", ""),
                        "sub_desc": item.get("sub_desc"),
                        "logo_url": item.get("logo_url")
                    })
                elif isinstance(item, str):
                    # Handle string format: "Live Chat"
                    processed_whats_included.append({
                        "title": item,
                        "sub_desc": None,
                        "logo_url": None
                    })
            
            # Process pricing plans to handle both array and single plan formats
            pricing_plans = club.get("pricing_plans", [])
            processed_pricing_plans = []
            
            if pricing_plans:
                for plan in pricing_plans:
                    if isinstance(plan, dict):
                        # Handle object format with all fields
                        processed_pricing_plans.append({
                            "frequency": plan.get("frequency", plan.get("plan", "")),
                            "price": plan.get("price", 0.0),
                            "currency": plan.get("currency", "USD"),
                            "stripe_product_id": plan.get("stripe_product_id"),
                            "stripe_price_id": plan.get("stripe_price_id"),
                            "is_active": plan.get("is_active", True)
                        })
                    else:
                        # Handle simple format
                        processed_pricing_plans.append({
                            "frequency": str(plan),
                            "price": 0.0,
                            "currency": "USD",
                            "stripe_product_id": None,
                            "stripe_price_id": None,
                            "is_active": True
                        })
            
            # Count active and inactive members from paid_members and members arrays
            paid_members = club.get("paid_members", [])
            members = club.get("members", [])
            
            active_members_count = 0
            inactive_members_count = 0
            
            # Count from paid_members array
            for member in paid_members:
                membership_status = member.get("membership_status", "inactive")
                if membership_status == "active":
                    active_members_count += 1
                else:
                    inactive_members_count += 1
            
            # Count from members array
            for member in members:
                membership_status = member.get("membership_status", "inactive")
                if membership_status == "active":
                    active_members_count += 1
                else:
                    inactive_members_count += 1
            
            logger.info(f"Club {club_name_based_id} has {active_members_count} active members and {inactive_members_count} inactive members")
            
            # Get club rejection information
            rejection_type = club.get("rejection_type")
            rejection_reason = club.get("rejection_reason")
            rejected_by = club.get("rejected_by")
            is_resubmit = club.get("is_resubmit")
            is_club_reject_temporary = club.get("is_club_reject_temporary")
            is_club_reject_permanently = club.get("is_club_reject_permanently")
            
            # Build response data
            club_detail = {
                "club_id": str(club["_id"]),
                "club_name": club.get("name", ""),
                "logo_url": club.get("logo_url"),
                "banner_url": club.get("banner_url"),
                "name_based_id": club.get("name_based_id", ""),
                "created_at": club.get("created_at"),
                "status": club.get("status", "pending"),
                "description": club.get("description", ""),
                "sub_description": club.get("sub_description"),
                "pricing_plan": club.get("pricing_plan"),
                "pricing_plans": processed_pricing_plans,
                "total_bets": total_bets,
                "win_pct": win_pct,
                "loss_pct": loss_pct,
                "total_wins": total_wins,
                "total_losses": total_losses,
                "total_spread": total_spread,
                "total_over_under": total_over_under,
                "total_moneyline": total_moneyline,
                "total_parlay": total_parlay,
                "pick_types": pick_types,
                "pick_type_counts": pick_type_counts,
                "whats_included": processed_whats_included,
                "top_3_sports": processed_sports,
                "total_revenue": total_revenue,
                "member_count": club.get("total_members", 0),
                "active_members_count": active_members_count,
                "inactive_members_count": inactive_members_count,
                "total_moderators": club.get("moderator_count", 0),
                "captain_id": club.get("captain_id", ""),
                "captain_full_name": captain_details.get("full_name", "Unknown Captain"),
                "captain_name_based_id": captain_details.get("name_based_id"),
                # User role (Captain, Moderator, or Member based on user's relationship to the club)
                "user_role": user_role,
                # Club rejection information
                "rejection_type": rejection_type,
                "rejection_reason": rejection_reason,
                "rejected_by": rejected_by,
                "is_resubmit": is_resubmit,
                "is_club_reject_temporary": is_club_reject_temporary,
                "is_club_reject_permanently": is_club_reject_permanently
            }
            
            logger.info(f"Successfully retrieved club detail for captain {captain_id}, club {club_name_based_id}")
            return True, club_detail, None
            
        except Exception as e:
            error_msg = f"Error getting captain club detail: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
    
    async def _calculate_club_betting_stats(self, club_id: str, captain_id: str) -> dict:
        """
        Calculate betting statistics for a club from club_picks table
        
        Args:
            club_id: Club ID
            captain_id: Captain's user ID
            
        Returns:
            dict: Betting statistics
        """
        try:
            from services.admin.db import club_picks_collection
            
            # club_picks stores club_id as name_based_id (e.g. "stripe-club"), not ObjectId
            # We need to get the name_based_id from the club document first
            from .db import get_club_collection
            club_collection = get_club_collection()
            club_doc = await club_collection.find_one({"_id": ObjectId(club_id)})
            club_name_based_id = club_doc.get("name_based_id") if club_doc else None
            
            if not club_name_based_id:
                logger.warning(f"Could not find name_based_id for club {club_id}")
                return {
                    "total_bets": 0,
                    "total_wins": 0,
                    "total_losses": 0,
                    "win_pct": 0.0,
                    "loss_pct": 0.0,
                    "total_spread": 0,
                    "total_over_under": 0,
                    "total_moneyline": 0,
                    "total_parlay": 0,
                    "pick_types": [],
                    "pick_type_counts": {}
                }
            
            logger.info(f"Querying club_picks with club_id: {club_name_based_id}, submitted_by: {captain_id}")
            
            # Single aggregation pipeline to calculate all betting stats
            pipeline = [
                {
                    "$match": {
                        "club_id": club_name_based_id,  # Use name_based_id, not ObjectId
                        # "submitted_by": captain_id   changes
                    }
                },
                {
                    "$facet": {
                        # Calculate total bets and results
                        "overall_stats": [
                            {
                                "$group": {
                                    "_id": None,
                                    "total_bets": {"$sum": 1},
                                    "total_wins": {
                                        "$sum": {
                                            "$cond": [{"$eq": ["$result", "win"]}, 1, 0]
                                        }
                                    },
                                    "total_losses": {
                                        "$sum": {
                                            "$cond": [{"$eq": ["$result", "loss"]}, 1, 0]
                                        }
                                    }
                                }
                            }
                        ],
                        # Calculate bet type breakdowns
                        "bet_types": [
                            {
                                "$group": {
                                    "_id": "$pick_type",
                                    "count": {"$sum": 1}
                                }
                            }
                        ]
                    }
                }
            ]
            
            result = await club_picks_collection.aggregate(pipeline).to_list(1)
            print(result,"resultresultresultresult")
            
            if not result or not result[0].get("overall_stats"):
                return {
                    "total_bets": 0,
                    "total_wins": 0,
                    "total_losses": 0,
                    "win_pct": 0.0,
                    "loss_pct": 0.0,
                    "total_spread": 0,
                    "total_over_under": 0,
                    "total_moneyline": 0,
                    "total_parlay": 0,
                    "pick_types": [],
                    "pick_type_counts": {}
                }
            
            # Extract overall stats
            overall = result[0]["overall_stats"][0] if result[0]["overall_stats"] else {}
            total_bets = overall.get("total_bets", 0)
            total_wins = overall.get("total_wins", 0)
            total_losses = overall.get("total_losses", 0)
            
            # Calculate percentages
            win_pct = (total_wins / total_bets * 100) if total_bets > 0 else 0.0
            loss_pct = (total_losses / total_bets * 100) if total_bets > 0 else 0.0
            
            # Extract bet type counts (filter out None values)
            bet_types = result[0].get("bet_types", [])
            bet_type_counts = {bt["_id"]: bt["count"] for bt in bet_types if bt.get("_id") is not None}
            print(bet_type_counts,"bet_type_countsbet_type_countsbet_type_counts")
            
            # Get unique pick types (list of all pick_type values)
            pick_types = list(bet_type_counts.keys())
            
            # Use bet_type_counts as pick_type_counts (they're the same data)
            pick_type_counts_dict = bet_type_counts.copy()
            
            total_spread = bet_type_counts.get("Spread", 0)
            total_over_under = bet_type_counts.get("Over/Under", 0) + bet_type_counts.get("Over/Under", 0)
            total_moneyline = bet_type_counts.get("Moneyline", 0)
            total_parlay = bet_type_counts.get("Parlay", 0)
            
            stats = {
                "total_bets": total_bets,
                "total_wins": total_wins,
                "total_losses": total_losses,
                "win_pct": round(win_pct, 2),
                "loss_pct": round(loss_pct, 2),
                "total_spread": total_spread,
                "total_over_under": total_over_under,
                "total_moneyline": total_moneyline,
                "total_parlay": total_parlay,
                "pick_types": pick_types,
                "pick_type_counts": pick_type_counts_dict
            }
            
            logger.info(f"Club {club_id} betting stats: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error calculating club betting stats: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "total_bets": 0,
                "total_wins": 0,
                "total_losses": 0,
                "win_pct": 0.0,
                "loss_pct": 0.0,
                "total_spread": 0,
                "total_over_under": 0,
                "total_moneyline": 0,
                "total_parlay": 0,
                "pick_types": [],
                "pick_type_counts": {}
            }
    
    async def _calculate_club_revenue(self, captain_id: str, club_id: str) -> float:
        """
        Calculate club-specific revenue from paid_members array
        
        Args:
            captain_id: Captain's user ID
            club_id: Club ID (ObjectId string)
            
        Returns:
            float: Total revenue for this specific club (captain's 95% share)
        """
        try:
            # Get club document with paid_members array
            from .db import get_club_collection
            club_collection = get_club_collection()
            club_doc = await club_collection.find_one({"_id": ObjectId(club_id)})
            
            if not club_doc:
                logger.warning(f"Club {club_id} not found")
                return 0.0
            
            club_name_based_id = club_doc.get("name_based_id", "")
            paid_members = club_doc.get("paid_members", [])
            
            logger.info(f"Calculating revenue for club {club_name_based_id} with {len(paid_members)} paid members")
            
            # Calculate total revenue from paid_members
            total_amount_paid = 0.0
            
            for member in paid_members:
                amount_paid = member.get("amount_paid", 0.0)
                if amount_paid > 0:
                    total_amount_paid += amount_paid
                    logger.info(f"Member {member.get('full_name', 'Unknown')}: ${amount_paid}")
            
            # Calculate captain's share (95%)
            your_share = total_amount_paid * 0.95
            platform_fee = total_amount_paid * 0.05
            
            logger.info(f"Club {club_name_based_id} - Total paid: ${total_amount_paid}, Platform fee (5%): ${platform_fee}, Your share (95%): ${your_share}")
            
            return your_share
                
        except Exception as e:
            logger.error(f"Error calculating club revenue: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return 0.0
    
    async def _calculate_club_revenue_from_payments(self, club_id: str) -> float:
        """
        Calculate club revenue from club_payments collection
        
        Args:
            club_id: Club ID (ObjectId string)
            
        Returns:
            float: Total revenue
        """
        try:
            from services.admin.db import club_payments_collection
            
            # Log to debug
            logger.info(f"Calculating revenue for club_id: {club_id}")
            
            # Try with ObjectId string first
            pipeline = [
                {
                    "$match": {
                        "club_id": club_id,
                        "payment_status": "succeeded"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total": {"$sum": "$amount"}
                    }
                }
            ]
            
            result = await club_payments_collection.aggregate(pipeline).to_list(1)
            print(f"Revenue result for club {club_id}: {result}")
            
            if result and result[0].get("total"):
                total_revenue = result[0].get("total", 0.0)
                logger.info(f"Calculated revenue from payments for club {club_id}: ${total_revenue}")
                return total_revenue
            
            # If no result, check all payments to see what club_id format is used
            logger.warning(f"No revenue found for club {club_id}, checking payment structure...")
            sample_payment = await club_payments_collection.find_one({})
            if sample_payment:
                logger.info(f"Sample payment structure: club_id={sample_payment.get('club_id')}, payment_status={sample_payment.get('payment_status')}")
            
            return 0.0
            
        except Exception as e:
            logger.error(f"Error calculating revenue from payments: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return 0.0