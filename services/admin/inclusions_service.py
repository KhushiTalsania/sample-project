from typing import Optional, List
from datetime import datetime
from bson import ObjectId
from .db import inclusions_collection
from .models import (
    InclusionCreateRequest, InclusionResponse, InclusionUpdateRequest,
    InclusionListResponse, InclusionDocument
)
import logging

logger = logging.getLogger(__name__)

class AdminInclusionsService:
    """Service for managing inclusions in the admin panel"""
    
    async def create_inclusion(self, inclusion_data: InclusionCreateRequest) -> Optional[InclusionResponse]:
        """Create a new inclusion"""
        try:
            # Check for duplicate title (case-insensitive)
            existing_inclusion = await inclusions_collection.find_one({
                "title": {"$regex": f"^{inclusion_data.title}$", "$options": "i"}
            })
            
            if existing_inclusion:
                logger.warning(f"Duplicate inclusion title detected: {inclusion_data.title}")
                raise ValueError(f"Inclusion with title '{inclusion_data.title}' already exists")
            
            now = datetime.utcnow()
            
            # Create inclusion document
            inclusion_doc = InclusionDocument(
                title=inclusion_data.title,
                sub_desc=inclusion_data.sub_desc,
                logo_url=inclusion_data.logo_url,
                created_at=now,
                updated_at=now
            )
            
            # Insert into database
            result = await inclusions_collection.insert_one(inclusion_doc.model_dump())
            
            if result.inserted_id:
                # Get the created inclusion
                created_inclusion = await inclusions_collection.find_one({"_id": result.inserted_id})
                return InclusionResponse(
                    id=str(created_inclusion["_id"]),
                    title=created_inclusion["title"],
                    sub_desc=created_inclusion["sub_desc"],
                    logo_url=created_inclusion.get("logo_url"),
                    created_at=created_inclusion["created_at"],
                    updated_at=created_inclusion["updated_at"]
                )
            
            return None
            
        except ValueError as e:
            # Re-raise ValueError for duplicate titles
            raise e
        except Exception as e:
            logger.error(f"Error creating inclusion: {e}")
            return None
    
    async def get_inclusion_by_id(self, inclusion_id: str) -> Optional[InclusionResponse]:
        """Get inclusion by ID"""
        try:
            inclusion_object_id = ObjectId(inclusion_id)
            inclusion = await inclusions_collection.find_one({"_id": inclusion_object_id})
            
            if inclusion:
                return InclusionResponse(
                    id=str(inclusion["_id"]),
                    title=inclusion["title"],
                    sub_desc=inclusion["sub_desc"],
                    logo_url=inclusion.get("logo_url"),
                    created_at=inclusion["created_at"],
                    updated_at=inclusion["updated_at"]
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting inclusion by ID: {e}")
            return None
    
    async def get_all_inclusions(
        self, 
        page: int = 1, 
        page_size: int = 20,
        search: Optional[str] = None
    ) -> InclusionListResponse:
        """Get all inclusions with pagination and search"""
        try:
            # Build query
            query = {}
            if search:
                query["$or"] = [
                    {"title": {"$regex": search, "$options": "i"}},
                    {"sub_desc": {"$regex": search, "$options": "i"}}
                ]
            
            # Get total count
            total_count = await inclusions_collection.count_documents(query)
            
            # Calculate pagination
            total_pages = (total_count + page_size - 1) // page_size
            skip = (page - 1) * page_size
            
            # Get inclusions
            cursor = inclusions_collection.find(query).sort([("created_at", -1)]).skip(skip).limit(page_size)
            inclusions_docs = await cursor.to_list(length=page_size)
            
            # Convert to response format
            inclusions = []
            for doc in inclusions_docs:
                inclusion_response = InclusionResponse(
                    id=str(doc["_id"]),
                    title=doc["title"],
                    sub_desc=doc["sub_desc"],
                    logo_url=doc.get("logo_url"),
                    created_at=doc["created_at"],
                    updated_at=doc["updated_at"]
                )
                inclusions.append(inclusion_response)
            
            result = InclusionListResponse(
                inclusions=inclusions,
                total_count=total_count,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting all inclusions: {e}")
            return InclusionListResponse(
                inclusions=[],
                total_count=0,
                page=page,
                page_size=page_size,
                total_pages=0,
                has_next=False,
                has_previous=False
            )
    
    async def update_inclusion(
        self, 
        inclusion_id: str, 
        inclusion_data: InclusionUpdateRequest
    ) -> Optional[InclusionResponse]:
        """Update an inclusion"""
        try:
            inclusion_object_id = ObjectId(inclusion_id)
            
            # Check for duplicate title if updating title
            if inclusion_data.title is not None:
                is_duplicate = await self.check_duplicate_title(inclusion_data.title, inclusion_id)
                if is_duplicate:
                    raise ValueError(f"Inclusion with title '{inclusion_data.title}' already exists")
            
            # Build update document
            update_doc = {"updated_at": datetime.utcnow()}
            
            if inclusion_data.title is not None:
                update_doc["title"] = inclusion_data.title
            
            if inclusion_data.sub_desc is not None:
                update_doc["sub_desc"] = inclusion_data.sub_desc
            
            if inclusion_data.logo_url is not None:
                update_doc["logo_url"] = inclusion_data.logo_url
            
            # Update inclusion
            result = await inclusions_collection.update_one(
                {"_id": inclusion_object_id},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                # Get updated inclusion
                updated_inclusion = await inclusions_collection.find_one({"_id": inclusion_object_id})
                return InclusionResponse(
                    id=str(updated_inclusion["_id"]),
                    title=updated_inclusion["title"],
                    sub_desc=updated_inclusion["sub_desc"],
                    logo_url=updated_inclusion.get("logo_url"),
                    created_at=updated_inclusion["created_at"],
                    updated_at=updated_inclusion["updated_at"]
                )
            
            return None
            
        except ValueError as e:
            # Re-raise ValueError for duplicate titles
            raise e
        except Exception as e:
            logger.error(f"Error updating inclusion: {e}")
            return None
    
    async def delete_inclusion(self, inclusion_id: str) -> bool:
        """Delete an inclusion"""
        try:
            inclusion_object_id = ObjectId(inclusion_id)
            
            result = await inclusions_collection.delete_one({"_id": inclusion_object_id})
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Error deleting inclusion: {e}")
            return False
    
    async def check_duplicate_title(self, title: str, exclude_id: Optional[str] = None) -> bool:
        """Check if an inclusion title already exists"""
        try:
            query = {"title": {"$regex": f"^{title}$", "$options": "i"}}
            
            if exclude_id:
                # Exclude current inclusion when updating
                query["_id"] = {"$ne": ObjectId(exclude_id)}
            
            existing = await inclusions_collection.find_one(query)
            return existing is not None
            
        except Exception as e:
            logger.error(f"Error checking duplicate title: {e}")
            return False
    
    async def get_inclusion_by_title(self, title: str) -> Optional[InclusionResponse]:
        """Get inclusion by title (case-insensitive)"""
        try:
            inclusion = await inclusions_collection.find_one({
                "title": {"$regex": f"^{title}$", "$options": "i"}
            })
            
            if inclusion:
                return InclusionResponse(
                    id=str(inclusion["_id"]),
                    title=inclusion["title"],
                    sub_desc=inclusion["sub_desc"],
                    logo_url=inclusion.get("logo_url"),
                    created_at=inclusion["created_at"],
                    updated_at=inclusion["updated_at"]
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting inclusion by title: {e}")
            return None
    
    async def get_all_titles(self) -> List[str]:
        """Get all inclusion titles for validation purposes"""
        try:
            cursor = inclusions_collection.find({}, {"title": 1, "_id": 0})
            titles = await cursor.to_list(length=None)
            return [doc["title"] for doc in titles]
        except Exception as e:
            logger.error(f"Error getting all titles: {e}")
            return []
    
    async def ensure_unique_index(self):
        """Ensure unique index exists on title field"""
        try:
            # Create unique index on title field (case-insensitive)
            await inclusions_collection.create_index(
                "title", 
                unique=True, 
                collation={"locale": "en", "strength": 2}
            )
            logger.info("Unique index created on inclusions.title field")
        except Exception as e:
            logger.warning(f"Could not create unique index on inclusions.title: {e}")
            # Index might already exist, which is fine

# Create service instance
admin_inclusions_service = AdminInclusionsService()

# Initialize unique index on startup
async def init_inclusions_service():
    """Initialize inclusions service with unique index"""
    try:
        await admin_inclusions_service.ensure_unique_index()
        logger.info("Inclusions service initialized with unique index")
    except Exception as e:
        logger.error(f"Failed to initialize inclusions service: {e}")

# Run initialization when module is imported
import asyncio
try:
    # Try to run the initialization
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # If loop is running, create a task
        loop.create_task(init_inclusions_service())
    else:
        # If no loop is running, run it directly
        asyncio.run(init_inclusions_service())
except Exception as e:
    logger.warning(f"Could not initialize inclusions service on import: {e}")
