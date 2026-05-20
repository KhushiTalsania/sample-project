"""
DateTime Utilities

This module provides utilities for handling datetime serialization
across the Stripe Connect services.
"""

from datetime import datetime
from typing import Any, Dict, List, Union, Optional

def serialize_datetime(obj: Any) -> Any:
    """
    Recursively serialize datetime objects in a data structure
    
    Args:
        obj: The object to serialize (dict, list, or any other type)
        
    Returns:
        The object with datetime objects converted to ISO format strings
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {key: serialize_datetime(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [serialize_datetime(item) for item in obj]
    else:
        return obj

def safe_datetime_serialize(obj: Any) -> Any:
    """
    Safely serialize datetime objects, handling None values
    
    Args:
        obj: The datetime object to serialize
        
    Returns:
        ISO format string or None
    """
    if obj is None:
        return None
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return obj

def format_stripe_datetime(stripe_datetime: Any) -> Optional[str]:
    """
    Format Stripe datetime objects to ISO format strings
    
    Args:
        stripe_datetime: Stripe datetime object (could be datetime or timestamp)
        
    Returns:
        ISO format string or None
    """
    if stripe_datetime is None:
        return None
    
    if isinstance(stripe_datetime, datetime):
        return stripe_datetime.isoformat()
    elif hasattr(stripe_datetime, 'isoformat'):
        return stripe_datetime.isoformat()
    else:
        # Handle Unix timestamps
        try:
            return datetime.fromtimestamp(stripe_datetime).isoformat()
        except (ValueError, TypeError):
            return None
