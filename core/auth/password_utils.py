"""
Centralized Password Utilities

This module provides unified password hashing and verification
functionality for all services.
"""

from passlib.context import CryptContext
import secrets
import string
from typing import Optional

class PasswordUtils:
    """
    Centralized password utilities for all services.
    
    This class provides consistent password hashing, verification,
    and generation across the entire monolithic application.
    """
    
    def __init__(self):
        # Password hashing context
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    def hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.
        
        Args:
            password: Plain text password to hash
            
        Returns:
            Hashed password string
        """
        return self.pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash.
        
        Args:
            plain_password: Plain text password to verify
            hashed_password: Hashed password to verify against
            
        Returns:
            True if password matches, False otherwise
        """
        return self.pwd_context.verify(plain_password, hashed_password)
    
    def generate_random_password(self, length: int = 12) -> str:
        """
        Generate a random secure password.
        
        Args:
            length: Length of password to generate
            
        Returns:
            Random password string
        """
        # Define character sets
        lowercase = string.ascii_lowercase
        uppercase = string.ascii_uppercase
        digits = string.digits
        special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        
        # Ensure at least one character from each set
        password = [
            secrets.choice(lowercase),
            secrets.choice(uppercase),
            secrets.choice(digits),
            secrets.choice(special_chars)
        ]
        
        # Fill the rest randomly
        all_chars = lowercase + uppercase + digits + special_chars
        for _ in range(length - 4):
            password.append(secrets.choice(all_chars))
        
        # Shuffle the password list
        secrets.SystemRandom().shuffle(password)
        
        return ''.join(password)
    
    def is_password_strong(self, password: str) -> tuple[bool, list[str]]:
        """
        Check if password meets strength requirements.
        
        Args:
            password: Password to check
            
        Returns:
            Tuple of (is_strong, list_of_issues)
        """
        issues = []
        
        if len(password) < 8:
            issues.append("Password must be at least 8 characters long")
        
        if not any(c.islower() for c in password):
            issues.append("Password must include at least one lowercase letter")
        
        if not any(c.isupper() for c in password):
            issues.append("Password must include at least one uppercase letter")
        
        if not any(c.isdigit() for c in password):
            issues.append("Password must include at least one number")
        
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            issues.append("Password must include at least one special character")
        
        return len(issues) == 0, issues

# Global password utils instance
_password_utils: Optional[PasswordUtils] = None

def get_password_utils() -> PasswordUtils:
    """Get the global password utils instance"""
    global _password_utils
    if _password_utils is None:
        _password_utils = PasswordUtils()
    return _password_utils 