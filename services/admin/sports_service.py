from typing import Optional, List
from datetime import datetime
from bson import ObjectId
from .db import sports_collection
from .models import (
    SportCreateRequest, SportResponse, SportUpdateRequest,
    SportListResponse, SportDocument
)
import logging

logger = logging.getLogger(__name__)

class AdminSportsService:
    """Service for managing sports in the admin panel"""
    
    async def create_sport(self, sport_data: SportCreateRequest) -> Optional[SportResponse]:
        """Create a new sport"""
        try:
            # Check for duplicate name (case-insensitive)
            existing_sport = await sports_collection.find_one({
                "name": {"$regex": f"^{sport_data.name}$", "$options": "i"}
            })
            
            if existing_sport:
                logger.warning(f"Duplicate sport name detected: {sport_data.name}")
                raise ValueError(f"Sport with name '{sport_data.name}' already exists")
            
            now = datetime.utcnow()
            
            # Create sport document
            sport_doc = SportDocument(
                name=sport_data.name,
                icon=sport_data.icon,
                created_at=now,
                updated_at=now
            )
            
            # Insert into database
            result = await sports_collection.insert_one(sport_doc.model_dump())
            
            if result.inserted_id:
                # Get the created sport
                created_sport = await sports_collection.find_one({"_id": result.inserted_id})
                return SportResponse(
                    id=str(created_sport["_id"]),
                    name=created_sport["name"],
                    icon=created_sport["icon"],
                    created_at=created_sport["created_at"],
                    updated_at=created_sport["updated_at"]
                )
            
            return None
            
        except ValueError as e:
            # Re-raise ValueError for duplicate names
            raise e
        except Exception as e:
            logger.error(f"Error creating sport: {e}")
            return None
    
    async def get_sport_by_id(self, sport_id: str) -> Optional[SportResponse]:
        """Get sport by ID"""
        try:
            sport_object_id = ObjectId(sport_id)
            sport = await sports_collection.find_one({"_id": sport_object_id})
            
            if sport:
                return SportResponse(
                    id=str(sport["_id"]),
                    name=sport["name"],
                    icon=sport["icon"],
                    created_at=sport["created_at"],
                    updated_at=sport["updated_at"]
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting sport by ID: {e}")
            return None
    
    async def get_all_sports(
        self, 
        page: int = 1, 
        page_size: int = 20,
        search: Optional[str] = None
    ) -> SportListResponse:
        """Get all sports with pagination and search"""
        try:
            # Build query
            query = {}
            if search:
                query["name"] = {"$regex": search, "$options": "i"}
            
            # Get total count
            total_count = await sports_collection.count_documents(query)
            
            # Calculate pagination
            total_pages = (total_count + page_size - 1) // page_size
            skip = (page - 1) * page_size
            
            # Get sports
            cursor = sports_collection.find(query).sort([("name", 1)]).skip(skip).limit(page_size)
            sports_docs = await cursor.to_list(length=page_size)
            
            # Convert to response format
            sports = []
            for doc in sports_docs:
                sports.append(SportResponse(
                    id=str(doc["_id"]),
                    name=doc["name"],
                    icon=doc["icon"],
                    created_at=doc["created_at"],
                    updated_at=doc["updated_at"]
                ))
            
            return SportListResponse(
                sports=sports,
                total_count=total_count,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1
            )
            
        except Exception as e:
            logger.error(f"Error getting all sports: {e}")
            return SportListResponse(
                sports=[],
                total_count=0,
                page=page,
                page_size=page_size,
                total_pages=0,
                has_next=False,
                has_previous=False
            )
    
    async def update_sport(
        self, 
        sport_id: str, 
        sport_data: SportUpdateRequest
    ) -> Optional[SportResponse]:
        """Update a sport"""
        try:
            sport_object_id = ObjectId(sport_id)
            
            # Check for duplicate name if updating name
            if sport_data.name is not None:
                is_duplicate = await self.check_duplicate_name(sport_data.name, sport_id)
                if is_duplicate:
                    raise ValueError(f"Sport with name '{sport_data.name}' already exists")
            
            # Build update document
            update_doc = {"updated_at": datetime.utcnow()}
            
            if sport_data.name is not None:
                update_doc["name"] = sport_data.name
            
            if sport_data.icon is not None:
                update_doc["icon"] = sport_data.icon
            
            # Update sport
            result = await sports_collection.update_one(
                {"_id": sport_object_id},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                # Get updated sport
                updated_sport = await sports_collection.find_one({"_id": sport_object_id})
                return SportResponse(
                    id=str(updated_sport["_id"]),
                    name=updated_sport["name"],
                    icon=updated_sport["icon"],
                    created_at=updated_sport["created_at"],
                    updated_at=updated_sport["updated_at"]
                )
            
            return None
            
        except ValueError as e:
            # Re-raise ValueError for duplicate names
            raise e
        except Exception as e:
            logger.error(f"Error updating sport: {e}")
            return None
    
    async def delete_sport(self, sport_id: str) -> bool:
        """Delete a sport"""
        try:
            sport_object_id = ObjectId(sport_id)
            
            result = await sports_collection.delete_one({"_id": sport_object_id})
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Error deleting sport: {e}")
            return False
    
    async def check_duplicate_name(self, name: str, exclude_id: Optional[str] = None) -> bool:
        """Check if a sport name already exists"""
        try:
            query = {"name": {"$regex": f"^{name}$", "$options": "i"}}
            
            if exclude_id:
                # Exclude current sport when updating
                query["_id"] = {"$ne": ObjectId(exclude_id)}
            
            existing = await sports_collection.find_one(query)
            return existing is not None
            
        except Exception as e:
            logger.error(f"Error checking duplicate name: {e}")
            return False
    
    async def get_sport_by_name(self, name: str) -> Optional[SportResponse]:
        """Get sport by name (case-insensitive)"""
        try:
            sport = await sports_collection.find_one({
                "name": {"$regex": f"^{name}$", "$options": "i"}
            })
            
            if sport:
                return SportResponse(
                    id=str(sport["_id"]),
                    name=sport["name"],
                    icon=sport["icon"],
                    created_at=sport["created_at"],
                    updated_at=sport["updated_at"]
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting sport by name: {e}")
            return None
    
    async def get_all_names(self) -> List[str]:
        """Get all sport names for validation purposes"""
        try:
            cursor = sports_collection.find({}, {"name": 1, "_id": 0})
            names = await cursor.to_list(length=None)
            return [doc["name"] for doc in names]
        except Exception as e:
            logger.error(f"Error getting all names: {e}")
            return []
    
    async def ensure_unique_index(self):
        """Ensure unique index exists on name field"""
        try:
            # Create unique index on name field (case-insensitive)
            await sports_collection.create_index(
                "name", 
                unique=True, 
                collation={"locale": "en", "strength": 2}
            )
            logger.info("Unique index created on sports.name field")
        except Exception as e:
            logger.warning(f"Could not create unique index on sports.name: {e}")
            # Index might already exist, which is fine

# Create service instance
admin_sports_service = AdminSportsService()

# Initialize unique index on startup
async def init_sports_service():
    """Initialize sports service with unique index"""
    try:
        await admin_sports_service.ensure_unique_index()
        logger.info("Sports service initialized with unique index")
    except Exception as e:
        logger.error(f"Failed to initialize sports service: {e}")

# Run initialization when module is imported
import asyncio
try:
    # Try to run the initialization
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # If loop is running, create a task
        loop.create_task(init_sports_service())
    else:
        # If no loop is running, run it directly
        asyncio.run(init_sports_service())
except Exception as e:
    logger.warning(f"Could not initialize sports service on import: {e}")
