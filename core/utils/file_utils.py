"""
Centralized File Utilities

This module provides unified file handling functionality for all services.
"""

import os
import uuid
import hashlib
from typing import Optional, List, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class FileUtils:
    """Centralized file utilities for all services"""
    
    def __init__(self):
        self.upload_base_dir = os.getenv('UPLOAD_BASE_DIR', 'uploads')
        self.max_file_size = int(os.getenv('MAX_FILE_SIZE', str(10 * 1024 * 1024)))  # 10MB default
        
        # Ensure upload directory exists
        Path(self.upload_base_dir).mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📁 File utils initialized: {self.upload_base_dir}")
    
    def generate_unique_filename(self, original_filename: str, prefix: str = "") -> str:
        """Generate unique filename while preserving extension"""
        name, ext = os.path.splitext(original_filename)
        unique_id = str(uuid.uuid4())
        return f"{prefix}{unique_id}{ext}" if prefix else f"{unique_id}{ext}"
    
    def get_file_hash(self, file_path: str) -> Optional[str]:
        """Get SHA256 hash of file"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.error(f"❌ Failed to get file hash: {e}")
            return None
    
    def get_safe_path(self, service: str, category: str, filename: str) -> str:
        """Get safe file path within upload directory"""
        safe_service = "".join(c for c in service if c.isalnum() or c in ('-', '_'))
        safe_category = "".join(c for c in category if c.isalnum() or c in ('-', '_'))
        safe_filename = "".join(c for c in filename if c.isalnum() or c in ('-', '_', '.'))
        
        return os.path.join(self.upload_base_dir, safe_service, safe_category, safe_filename)
    
    def ensure_directory(self, file_path: str) -> bool:
        """Ensure directory exists for file path"""
        try:
            directory = os.path.dirname(file_path)
            Path(directory).mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"❌ Failed to create directory: {e}")
            return False
    
    def is_allowed_file_type(self, filename: str, allowed_extensions: List[str]) -> bool:
        """Check if file type is allowed"""
        ext = os.path.splitext(filename)[1].lower()
        return ext in [f".{ext.lower()}" for ext in allowed_extensions]
    
    def delete_file(self, file_path: str) -> bool:
        """Safely delete file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"🗑️ File deleted: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Failed to delete file {file_path}: {e}")
            return False

# Global file utils instance
_file_utils: Optional[FileUtils] = None

def get_file_utils() -> FileUtils:
    """Get the global file utils instance"""
    global _file_utils
    if _file_utils is None:
        _file_utils = FileUtils()
    return _file_utils 