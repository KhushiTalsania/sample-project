"""
Centralized Validation Utilities

This module provides unified validation functionality for all services.
"""

import re
from typing import Optional, List, Dict, Any, Tuple
from email_validator import validate_email, EmailNotValidError
import logging

logger = logging.getLogger(__name__)

class ValidationUtils:
    """Centralized validation utilities for all services"""
    
    def __init__(self):
        # Common regex patterns
        self.phone_pattern = re.compile(r'^\+?[1-9]\d{1,14}$')
        self.name_pattern = re.compile(r'^[A-Za-z\s\-\'\.]{1,50}$')
        self.username_pattern = re.compile(r'^[A-Za-z0-9_\-]{3,30}$')
        self.password_pattern = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$')
    
    def validate_email_address(self, email: str) -> Tuple[bool, Optional[str]]:
        """Validate email address"""
        try:
            validated_email = validate_email(email)
            return True, validated_email.email
        except EmailNotValidError as e:
            return False, str(e)
    
    def validate_phone_number(self, phone: str) -> Tuple[bool, Optional[str]]:
        """Validate phone number format"""
        cleaned_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
        
        if not cleaned_phone:
            return False, "Phone number must contain digits"
        
        if self.phone_pattern.match(cleaned_phone):
            return True, cleaned_phone
        else:
            return False, "Invalid phone number format"
    
    def validate_password_strength(self, password: str) -> Tuple[bool, List[str]]:
        """Validate password strength"""
        issues = []
        
        if len(password) < 8:
            issues.append("Password must be at least 8 characters long")
        
        if not re.search(r'[a-z]', password):
            issues.append("Password must include at least one lowercase letter")
        
        if not re.search(r'[A-Z]', password):
            issues.append("Password must include at least one uppercase letter")
        
        if not re.search(r'\d', password):
            issues.append("Password must include at least one number")
        
        if not re.search(r'[@$!%*?&]', password):
            issues.append("Password must include at least one special character (@$!%*?&)")
        
        return len(issues) == 0, issues
    
    def validate_name(self, name: str, field_name: str = "Name") -> Tuple[bool, Optional[str]]:
        """Validate name format"""
        if not name or not name.strip():
            return False, f"{field_name} cannot be empty"
        
        if len(name.strip()) < 1:
            return False, f"{field_name} must be at least 1 character long"
        
        if len(name.strip()) > 50:
            return False, f"{field_name} must be at most 50 characters long"
        
        if self.name_pattern.match(name.strip()):
            return True, name.strip()
        else:
            return False, f"{field_name} contains invalid characters"
    
    def validate_username(self, username: str) -> Tuple[bool, Optional[str]]:
        """Validate username format"""
        if not username or not username.strip():
            return False, "Username cannot be empty"
        
        username = username.strip().lower()
        
        if len(username) < 3:
            return False, "Username must be at least 3 characters long"
        
        if len(username) > 30:
            return False, "Username must be at most 30 characters long"
        
        if self.username_pattern.match(username):
            return True, username
        else:
            return False, "Username can only contain letters, numbers, underscores, and hyphens"
    
    def validate_required_fields(self, data: Dict[str, Any], required_fields: List[str]) -> Tuple[bool, List[str]]:
        """Validate that all required fields are present and not empty"""
        missing_fields = []
        
        for field in required_fields:
            if field not in data or not data[field] or (isinstance(data[field], str) and not data[field].strip()):
                missing_fields.append(field)
        
        return len(missing_fields) == 0, missing_fields
    
    def sanitize_string(self, value: str, max_length: int = 255) -> str:
        """Sanitize string input"""
        if not value:
            return ""
        
        # Remove null bytes and control characters
        sanitized = ''.join(char for char in value if ord(char) >= 32 or char in '\n\r\t')
        
        # Trim whitespace and limit length
        return sanitized.strip()[:max_length]
    
    def validate_url(self, url: str) -> Tuple[bool, Optional[str]]:
        """Validate URL format"""
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        
        if url_pattern.match(url):
            return True, url
        else:
            return False, "Invalid URL format"

# Global validation utils instance
_validation_utils: Optional[ValidationUtils] = None

def get_validation_utils() -> ValidationUtils:
    """Get the global validation utils instance"""
    global _validation_utils
    if _validation_utils is None:
        _validation_utils = ValidationUtils()
    return _validation_utils 