import re
import uuid
from typing import Optional

def generate_name_based_id(name: str) -> str:
    """
    Generate a URL-friendly ID based on the club name.
    
    Args:
        name: The club name
        
    Returns:
        A URL-friendly string in the format: lowercase-name-with-hyphens
    """
    # Convert to lowercase
    name_lower = name.lower()
    
    # Replace spaces and special characters with hyphens
    # Keep only alphanumeric characters and hyphens
    name_clean = re.sub(r'[^a-z0-9\s-]', '', name_lower)
    
    # Replace multiple spaces with single hyphens
    name_clean = re.sub(r'\s+', '-', name_clean)
    
    # Remove leading/trailing hyphens
    name_clean = name_clean.strip('-')
    
    # If the result is empty or too short, add a random suffix
    if len(name_clean) < 3:
        name_clean = f"club-{str(uuid.uuid4())[:8]}"
    
    return name_clean

def is_valid_name_based_id(name_based_id: str) -> bool:
    """
    Check if a name_based_id is valid.
    
    Args:
        name_based_id: The ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not name_based_id:
        return False
    
    # Check if it contains only lowercase letters, numbers, and hyphens
    if not re.match(r'^[a-z0-9-]+$', name_based_id):
        return False
    
    # Check if it starts or ends with a hyphen
    if name_based_id.startswith('-') or name_based_id.endswith('-'):
        return False
    
    # Check if it's at least 3 characters long
    if len(name_based_id) < 3:
        return False
    
    return True
