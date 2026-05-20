"""
Image Upload Service for Betting Club Service
Handles file uploads, validation, and storage
"""

import os
import uuid
import shutil
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from pathlib import Path
import aiofiles
from PIL import Image
import io
from fastapi import UploadFile, HTTPException, status
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ImageUploadService:
    """Service for handling image uploads"""
    
    def __init__(self):
        # Base upload directory
        self.base_upload_dir = Path("uploads")
        self.base_upload_dir.mkdir(exist_ok=True)
        
        # Base URL for generating full image URLs
        self.base_url = os.getenv('ADMIN_BASE_URL', 'https://api.simbet.websitetestingbox.com/admin')
        
        # Create subdirectories for different image types
        self.upload_dirs = {
            "club_logo": self.base_upload_dir / "club_logos",
            "club_banner": self.base_upload_dir / "club_banners", 
            "user_avatar": self.base_upload_dir / "user_avatars",
            "club_gallery": self.base_upload_dir / "club_gallery",
            "general": self.base_upload_dir / "general"
        }
        
        # Create all directories
        for dir_path in self.upload_dirs.values():
            dir_path.mkdir(exist_ok=True)
        
        # Allowed file types
        self.allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        self.allowed_mime_types = {
            'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'
        }
        
        # File size limits (in bytes)
        self.max_file_size = 10 * 1024 * 1024  # 10MB
        
        # Image dimension limits
        self.max_dimensions = (4000, 4000)  # max width, height
        self.min_dimensions = (100, 100)    # min width, height
        
        logger.info(f"ImageUploadService initialized. Base directory: {self.base_upload_dir.absolute()}")
        logger.info(f"Base URL for images: {self.base_url}")
    
    async def validate_file(self, file: UploadFile) -> Tuple[bool, str]:
        """
        Validate uploaded file
        Returns: (is_valid, error_message)
        """
        try:
            # Check file size
            if file.size and file.size > self.max_file_size:
                return False, f"File size ({file.size} bytes) exceeds maximum allowed size ({self.max_file_size} bytes)"
            
            # Check file extension
            file_extension = Path(file.filename).suffix.lower()
            if file_extension not in self.allowed_extensions:
                return False, f"File extension '{file_extension}' not allowed. Allowed: {', '.join(self.allowed_extensions)}"
            
            # Check MIME type
            if file.content_type not in self.allowed_mime_types:
                return False, f"File type '{file.content_type}' not allowed. Allowed: {', '.join(self.allowed_mime_types)}"
            
            # Check if filename is provided
            if not file.filename:
                return False, "No filename provided"
            
            return True, ""
            
        except Exception as e:
            logger.error(f"Error validating file: {str(e)}")
            return False, f"File validation error: {str(e)}"
    
    async def process_image(self, file: UploadFile, purpose: str, 
                          resize: bool = True, max_width: int = 800, 
                          max_height: int = 800, quality: int = 85) -> Dict[str, Any]:
        """
        Process and save uploaded image
        """
        try:
            # Validate file
            is_valid, error_msg = await self.validate_file(file)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_msg
                )
            
            # Generate unique filename
            file_extension = Path(file.filename).suffix.lower()
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            
            # Determine upload directory
            upload_dir = self.upload_dirs.get(purpose, self.upload_dirs["general"])
            
            # Create full file path
            file_path = upload_dir / unique_filename
            
            # Read file content
            content = await file.read()
            
            # Process image if resize is enabled
            if resize:
                try:
                    # Open image with PIL
                    img = Image.open(io.BytesIO(content))
                    
                    # Get original dimensions
                    original_width, original_height = img.size
                    
                    # Resize if needed
                    if original_width > max_width or original_height > max_height:
                        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                        new_width, new_height = img.size
                        logger.info(f"Resized image from {original_width}x{original_height} to {new_width}x{new_height}")
                    
                    # Convert to RGB if necessary (for JPEG)
                    if file_extension in ['.jpg', '.jpeg'] and img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Save processed image
                    img_buffer = io.BytesIO()
                    if file_extension in ['.jpg', '.jpeg']:
                        img.save(img_buffer, format='JPEG', quality=quality, optimize=True)
                    else:
                        img.save(img_buffer, format=img.format or 'PNG', optimize=True)
                    
                    content = img_buffer.getvalue()
                    final_dimensions = img.size
                    
                except Exception as e:
                    logger.warning(f"Image processing failed, saving original: {str(e)}")
                    final_dimensions = None
            else:
                final_dimensions = None
            
            # Save file
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content)
            
            # Get final file size
            final_file_size = len(content)
            
            # Generate public URL
            image_url = f"{self.base_url}/uploads/{purpose}/{unique_filename}"
            
            # Prepare metadata
            metadata = {
                "original_filename": file.filename,
                "file_size_bytes": final_file_size,
                "content_type": file.content_type,
                "dimensions": final_dimensions,
                "upload_purpose": purpose,
                "processed": resize,
                "max_dimensions": (max_width, max_height) if resize else None
            }
            
            logger.info(f"Image uploaded successfully: {file_path} ({final_file_size} bytes)")
            
            return {
                "image_url": image_url,
                "image_id": str(uuid.uuid4()),
                "filename": unique_filename,
                "file_size": final_file_size,
                "content_type": file.content_type,
                "upload_timestamp": datetime.utcnow(),
                "metadata": metadata,
                "file_path": str(file_path)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing image: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process image: {str(e)}"
            )
    
    async def delete_image(self, image_path: str) -> bool:
        """
        Delete an uploaded image
        """
        try:
            # Remove base URL and /uploads/ prefix if present
            if image_path.startswith(self.base_url):
                image_path = image_path[len(self.base_url):]
            if image_path.startswith('/uploads/'):
                image_path = image_path[8:]  # Remove '/uploads/'
            
            # Construct full path
            full_path = self.base_upload_dir / image_path
            
            # Check if file exists
            if not full_path.exists():
                logger.warning(f"Image file not found: {full_path}")
                return False
            
            # Delete file
            full_path.unlink()
            logger.info(f"Image deleted successfully: {full_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting image: {str(e)}")
            return False
    
    def get_image_info(self, image_path: str) -> Optional[Dict[str, Any]]:
        """
        Get information about an uploaded image
        """
        try:
            # Remove base URL and /uploads/ prefix if present
            if image_path.startswith(self.base_url):
                image_path = image_path[len(self.base_url):]
            if image_path.startswith('/uploads/'):
                image_path = image_path[8:]  # Remove '/uploads/'
            
            # Construct full path
            full_path = self.base_upload_dir / image_path
            
            # Check if file exists
            if not full_path.exists():
                return None
            
            # Get file stats
            stat = full_path.stat()
            
            return {
                "filename": full_path.name,
                "file_size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_ctime),
                "modified_at": datetime.fromtimestamp(stat.st_mtime),
                "file_path": str(full_path),
                "full_url": f"{self.base_url}/uploads/{image_path}"
            }
            
        except Exception as e:
            logger.error(f"Error getting image info: {str(e)}")
            return None
    
    def get_full_url(self, relative_path: str) -> str:
        """
        Convert a relative upload path to a full URL
        """
        # Remove /uploads/ prefix if present
        if relative_path.startswith('/uploads/'):
            relative_path = relative_path[8:]
        
        return f"{self.base_url}/uploads/{relative_path}"
    
    def cleanup_old_files(self, max_age_days: int = 30) -> int:
        """
        Clean up old uploaded files
        Returns: number of files deleted
        """
        try:
            deleted_count = 0
            current_time = datetime.now()
            
            for upload_dir in self.upload_dirs.values():
                if not upload_dir.exists():
                    continue
                
                for file_path in upload_dir.iterdir():
                    if file_path.is_file():
                        # Check file age
                        file_age = current_time - datetime.fromtimestamp(file_path.stat().st_ctime)
                        
                        if file_age.days > max_age_days:
                            try:
                                file_path.unlink()
                                deleted_count += 1
                                logger.info(f"Deleted old file: {file_path}")
                            except Exception as e:
                                logger.error(f"Error deleting old file {file_path}: {str(e)}")
            
            logger.info(f"Cleanup completed. Deleted {deleted_count} old files")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            return 0

# Global instance
image_service = ImageUploadService()
