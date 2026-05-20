import re
from typing import Optional
from bson import ObjectId

def generate_name_based_id(name: str, existing_ids: list = None) -> str:
    """
    Generate a URL-friendly ID based on the name.
    Converts "The King of Kurtz" to "the-king-of-kurtz"
    If the ID already exists, appends the last 4 digits of the original ID.
    
    Args:
        name: The original name
        existing_ids: List of existing IDs to check for duplicates
    
    Returns:
        A URL-friendly ID string
    """
    # Convert to lowercase and replace spaces/special chars with hyphens
    base_id = re.sub(r'[^a-zA-Z0-9\s]', '', name.lower())
    base_id = re.sub(r'\s+', '-', base_id.strip())
    
    # Remove leading/trailing hyphens
    base_id = base_id.strip('-')
    
    # If no existing IDs provided or base_id is unique, return it
    if not existing_ids or base_id not in existing_ids:
        return base_id
    
    # If base_id exists, we need to append something to make it unique
    # For now, we'll append a placeholder that will be replaced with actual ID digits
    return f"{base_id}-xxxx"

def generate_unique_name_based_id(name: str, original_id: str, existing_ids: list = None) -> str:
    """
    Generate a unique name-based ID, appending the last 4 digits of the original ID if needed.
    
    Args:
        name: The original name
        original_id: The original MongoDB ObjectId string
        existing_ids: List of existing IDs to check for duplicates
    
    Returns:
        A unique URL-friendly ID string
    """
    base_id = generate_name_based_id(name, existing_ids)
    
    # If base_id is unique, return it
    if not existing_ids or base_id not in existing_ids:
        return base_id
    
    # Extract last 4 characters from original ID
    if len(original_id) >= 4:
        suffix = original_id[-4:]
    else:
        suffix = original_id
    
    unique_id = f"{base_id}-{suffix}"
    
    # If this is still not unique, append more characters
    counter = 1
    while existing_ids and unique_id in existing_ids:
        unique_id = f"{base_id}-{suffix}-{counter}"
        counter += 1
    
    return unique_id

def extract_original_id_from_name_based_id(name_based_id: str) -> Optional[str]:
    """
    Extract the original MongoDB ObjectId from a name-based ID.
    This is a reverse lookup function for when we need to find the original ID.
    
    Args:
        name_based_id: The name-based ID (e.g., "the-king-of-kurtz-abcd")
    
    Returns:
        The original ObjectId string if found, None otherwise
    """
    # This function would need to be implemented based on how you store the mapping
    # For now, we'll return None as this would require a lookup table
    return None

def is_valid_name_based_id(name_based_id: str) -> bool:
    """
    Check if a name-based ID is valid.
    
    Args:
        name_based_id: The ID to validate
    
    Returns:
        True if valid, False otherwise
    """
    # Check if it matches the pattern: lowercase letters, numbers, hyphens
    pattern = r'^[a-z0-9]+(-[a-z0-9]+)*$'
    return bool(re.match(pattern, name_based_id))
