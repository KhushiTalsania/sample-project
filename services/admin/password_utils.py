"""
Admin Service Password Utilities

This module uses centralized password utilities while maintaining
backward compatibility with the admin service.
"""

from core.auth.password_utils import get_password_utils
from typing import Optional, Union

# Get centralized password utils
password_utils = get_password_utils()

class PasswordHasher:
    """Utility class for password hashing and verification using centralized components."""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a plain text password using centralized password utils.
        
        Args:
            password (str): The plain text password to hash
            
        Returns:
            str: The hashed password as a string
        """
        return password_utils.hash_password(password)
    
    @staticmethod
    def verify_password(password: str, hashed_password: str) -> bool:
        """
        Verify a plain text password against a hashed password using centralized utils.
        
        Args:
            password (str): The plain text password to verify
            hashed_password (str): The hashed password to verify against
            
        Returns:
            bool: True if the password matches, False otherwise
        """
        return password_utils.verify_password(password, hashed_password)
    
    @staticmethod
    def generate_secure_password(length: int = 12) -> str:
        """
        Generate a secure random password using centralized utils.
        
        Args:
            length (int): The length of the password to generate (default: 12)
            
        Returns:
            str: A secure random password
        """
        return password_utils.generate_random_password(length)
    
    @staticmethod
    def is_password_strong(password: str) -> tuple[bool, list[str]]:
        """
        Check if a password meets strength requirements using centralized utils.
        
        Args:
            password (str): The password to check
            
        Returns:
            tuple[bool, list[str]]: A tuple containing:
                - bool: True if password is strong, False otherwise
                - list[str]: List of issues with the password (empty if strong)
        """
        return password_utils.is_password_strong(password)

# For backward compatibility, provide the same interface
def hash_password(password: str) -> str:
    """Hash password using centralized utils"""
    return password_utils.hash_password(password)

def verify_password(password: str, hashed_password: str) -> bool:
    """Verify password using centralized utils"""
    return password_utils.verify_password(password, hashed_password)

def generate_secure_password(length: int = 12) -> str:
    """Generate secure password using centralized utils"""
    return password_utils.generate_random_password(length)

def is_password_strong(password: str) -> tuple[bool, list[str]]:
    """Check password strength using centralized utils"""
    return password_utils.is_password_strong(password)