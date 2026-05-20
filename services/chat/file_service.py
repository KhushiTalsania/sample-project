import os
import uuid
import aiofiles
from datetime import datetime
from typing import List, Optional, Tuple
from fastapi import UploadFile, HTTPException, status
from bson import ObjectId

from .db import get_database
from .models import FileType, FileInfo

# File upload configuration
UPLOAD_DIR = "uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"]
ALLOWED_VIDEO_TYPES = ["video/mp4", "video/avi", "video/mov", "video/wmv", "video/flv"]
ALLOWED_DOCUMENT_TYPES = ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 
                          "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          "text/plain", "application/zip", "application/x-rar-compressed"]

class FileService:
    def __init__(self):
        self.db = get_database()
        self.files_collection = self.db["files"]
        self._ensure_upload_dir()
    
    def _ensure_upload_dir(self):
        """Ensure upload directory exists"""
        if not os.path.exists(UPLOAD_DIR):
            os.makedirs(UPLOAD_DIR)
        
        # Create subdirectories for different file types
        for file_type in FileType:
            type_dir = os.path.join(UPLOAD_DIR, file_type.value)
            if not os.path.exists(type_dir):
                os.makedirs(type_dir)
    
    async def validate_file(self, file: UploadFile, file_type: FileType) -> Tuple[bool, str]:
        """Validate uploaded file"""
        # Check file size
        if file.size and file.size > MAX_FILE_SIZE:
            return False, f"File size exceeds maximum limit of {MAX_FILE_SIZE // (1024*1024)}MB"
        
        # Check file type
        mime_type = file.content_type
        if file_type == FileType.IMAGE and mime_type not in ALLOWED_IMAGE_TYPES:
            return False, f"Invalid image type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}"
        elif file_type == FileType.VIDEO and mime_type not in ALLOWED_VIDEO_TYPES:
            return False, f"Invalid video type. Allowed: {', '.join(ALLOWED_VIDEO_TYPES)}"
        elif file_type == FileType.DOCUMENT and mime_type not in ALLOWED_DOCUMENT_TYPES:
            return False, f"Invalid document type. Allowed: {', '.join(ALLOWED_DOCUMENT_TYPES)}"
        
        return True, "File is valid"
    
    async def save_file(self, file: UploadFile, file_type: FileType, user_id: str, club_id: str, 
                       title: Optional[str] = None, description: Optional[str] = None, 
                       tags: List[str] = None) -> FileInfo:
        """Save uploaded file and return file info"""
        
        # Validate file
        is_valid, error_msg = await self.validate_file(file, file_type)
        if not is_valid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
        
        # Generate unique filename
        file_id = str(uuid.uuid4())
        file_extension = os.path.splitext(file.filename)[1] if file.filename else ""
        filename = f"{file_id}{file_extension}"
        
        # Create file path
        file_path = os.path.join(UPLOAD_DIR, file_type.value, filename)
        
        # Save file to disk
        try:
            async with aiofiles.open(file_path, 'wb') as f:
                content = await file.read()
                await f.write(content)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                              detail=f"Failed to save file: {str(e)}")
        
        # Get file size
        file_size = len(content)
        
        # Create file URL (in production, this would be a CDN URL)
        file_url = f"/uploads/{file_type.value}/{filename}"
        
        # Save file info to database
        file_info = {
            "file_id": file_id,
            "file_url": file_url,
            "file_path": file_path,
            "file_type": file_type.value,
            "original_filename": file.filename,
            "title": title,
            "description": description,
            "tags": tags or [],
            "uploaded_by": user_id,
            "club_id": club_id,
            "uploaded_at": datetime.utcnow(),
            "file_size": file_size,
            "mime_type": file.content_type,
            "is_deleted": False
        }
        
        await self.files_collection.insert_one(file_info)
        
        # Get user info for response
        users_collection = self.db["users"]
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        username = user.get("username", "Unknown") if user else "Unknown"
        
        return FileInfo(
            file_id=file_id,
            file_url=file_url,
            file_type=file_type,
            title=title,
            description=description,
            uploaded_by=user_id,
            uploaded_by_username=username,
            uploaded_at=file_info["uploaded_at"],
            file_size=file_size,
            mime_type=file.content_type,
            tags=tags or []
        )
    
    async def get_club_files(self, club_id: str, file_type: Optional[FileType] = None, 
                            page: int = 1, page_size: int = 20) -> Tuple[List[FileInfo], int]:
        """Get files uploaded to a club"""
        query = {"club_id": club_id, "is_deleted": False}
        if file_type:
            query["file_type"] = file_type.value
        
        # Get total count
        total_count = await self.files_collection.count_documents(query)
        
        # Get files with pagination
        skip = (page - 1) * page_size
        cursor = self.files_collection.find(query).sort("uploaded_at", -1).skip(skip).limit(page_size)
        
        files = []
        async for file_doc in cursor:
            # Get user info
            users_collection = self.db["users"]
            user = await users_collection.find_one({"_id": ObjectId(file_doc["uploaded_by"])})
            username = user.get("username", "Unknown") if user else "Unknown"
            
            files.append(FileInfo(
                file_id=file_doc["file_id"],
                file_url=file_doc["file_url"],
                file_type=FileType(file_doc["file_type"]),
                title=file_doc.get("title"),
                description=file_doc.get("description"),
                uploaded_by=file_doc["uploaded_by"],
                uploaded_by_username=username,
                uploaded_at=file_doc["uploaded_at"],
                file_size=file_doc["file_size"],
                mime_type=file_doc["mime_type"],
                tags=file_doc.get("tags", [])
            ))
        
        return files, total_count
    
    async def get_file_by_id(self, file_id: str) -> Optional[FileInfo]:
        """Get file info by ID"""
        file_doc = await self.files_collection.find_one({"file_id": file_id, "is_deleted": False})
        if not file_doc:
            return None
        
        # Get user info
        users_collection = self.db["users"]
        user = await users_collection.find_one({"_id": ObjectId(file_doc["uploaded_by"])})
        username = user.get("username", "Unknown") if user else "Unknown"
        
        return FileInfo(
            file_id=file_doc["file_id"],
            file_url=file_doc["file_url"],
            file_type=FileType(file_doc["file_type"]),
            title=file_doc.get("title"),
            description=file_doc.get("description"),
            uploaded_by=file_doc["uploaded_by"],
            uploaded_by_username=username,
            uploaded_at=file_doc["uploaded_at"],
            file_size=file_doc["file_size"],
            mime_type=file_doc["mime_type"],
            tags=file_doc.get("tags", [])
        )
    
    async def delete_file(self, file_id: str, user_id: str) -> bool:
        """Delete a file (soft delete)"""
        file_doc = await self.files_collection.find_one({"file_id": file_id})
        if not file_doc:
            return False
        
        # Check if user can delete (uploader or moderator/captain)
        if file_doc["uploaded_by"] != user_id:
            # Check if user is moderator/captain
            user_access_collection = self.db["user_access"]
            access = await user_access_collection.find_one({
                "user_id": user_id,
                "club_id": file_doc["club_id"]
            })
            if not access or access.get("role") not in ["captain", "moderator"]:
                return False
        
        # Soft delete
        await self.files_collection.update_one(
            {"file_id": file_id},
            {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow(), "deleted_by": user_id}}
        )
        
        return True

# Global file service instance
file_service = FileService() 