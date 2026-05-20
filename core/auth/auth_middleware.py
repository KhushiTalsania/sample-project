"""
Centralized Authentication Middleware

This module provides unified authentication middleware that can be used
across all services in the monolithic application.
"""

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId
from typing import Dict, Optional
import logging
from datetime import datetime, timezone

from .jwt_handler import get_jwt_handler
from ..database.collections import get_collections

logger = logging.getLogger(__name__)

# Security scheme for JWT authentication
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """
    Get current user from JWT token with centralized authentication.
    
    This function provides unified user authentication across all services.
    It handles token validation, user lookup, and session management.
    
    Args:
        credentials: HTTP Bearer token credentials
        
    Returns:
        User data dictionary
        
    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    jwt_handler = get_jwt_handler()
    collections = get_collections()
    
    # Verify token
    payload = jwt_handler.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user_id from payload
    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user ID",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if token is blacklisted (if session management is enabled)
    try:
        blacklist_collection = collections.get_session_blacklist_collection()
        blacklisted = await blacklist_collection.find_one({"token": token})
        if blacklisted:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been invalidated",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except Exception as e:
        logger.warning(f"Could not check token blacklist: {e}")
        # Continue without blacklist check if collection doesn't exist
    
    # Convert string user_id to ObjectId for MongoDB query
    try:
        object_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: invalid user ID format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Find user in database
    users_collection = collections.get_users_collection()
    user = await users_collection.find_one({"_id": object_id})
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update session activity (if session management is enabled)
    try:
        activity_collection = collections.get_session_activity_collection()
        await activity_collection.update_one(
            {"user_id": user_id, "token": token},
            {
                "$set": {
                    "last_activity": datetime.now(timezone.utc),
                    "user_agent": credentials.headers.get("User-Agent", "Unknown") if hasattr(credentials, 'headers') else "Unknown"
                }
            },
            upsert=True
        )
    except Exception as e:
        logger.warning(f"Could not update session activity: {e}")
        # Continue without session activity update if collection doesn't exist
    
    return {
        "user_id": str(user["_id"]),
        "full_name": user.get("full_name", ""),
        "email": user.get("email", ""),
        "role": user.get("role", "Member"),
        "avatar_url": user.get("avatar_url"),
        "membership_status": user.get("membership_status", "inactive"),
        "membership_type": user.get("membership_type", "none"),
        "is_active": user.get("is_active", True)
    }

async def get_current_user_or_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """
    Get current user or admin from JWT token.
    
    This function supports both regular users and admin users for endpoints
    that can be accessed by both (like notifications).
    
    Args:
        credentials: HTTP Bearer token credentials
        
    Returns:
        User/Admin data dictionary with 'user_type' field
        
    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    jwt_handler = get_jwt_handler()
    collections = get_collections()
    
    # Verify token
    payload = jwt_handler.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user/admin ID from payload
    user_id = payload.get("sub") or payload.get("user_id") or payload.get("admin_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user ID",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Try to find as regular user first
    try:
        object_id = ObjectId(user_id)
        users_collection = collections.get_users_collection()
        user = await users_collection.find_one({"_id": object_id})
        
        if user and user.get("is_active", True):
            return {
                "user_id": str(user["_id"]),
                "full_name": user.get("full_name", ""),
                "email": user.get("email", ""),
                "role": user.get("role", "Member"),
                "avatar_url": user.get("avatar_url"),
                "membership_status": user.get("membership_status", "inactive"),
                "membership_type": user.get("membership_type", "none"),
                "is_active": user.get("is_active", True),
                "user_type": "user"
            }
    except Exception:
        pass  # Not a valid ObjectId or user not found, try admin
    
    # Try to find as admin (by ObjectId or email)
    admins_collection = collections.get_admins_collection()
    
    # Try ObjectId-based lookup
    try:
        object_id = ObjectId(user_id)
        admin = await admins_collection.find_one({"_id": object_id})
    except Exception:
        admin = None
    
    # Fallback: try email-based lookup
    if not admin:
        admin = await admins_collection.find_one({"email": user_id})
    
    if admin and admin.get("is_active", True):
        return {
            "user_id": str(admin["_id"]),
            "full_name": admin.get("name", ""),
            "email": admin.get("email", ""),
            "role": admin.get("role", "admin"),
            "avatar_url": admin.get("avatar_url"),
            "is_active": admin.get("is_active", True),
            "user_type": "admin"
        }
    
    # Neither user nor admin found
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User or admin not found",
        headers={"WWW-Authenticate": "Bearer"},
    )

async def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """
    Get current admin from JWT token with centralized authentication.
    
    This function provides unified admin authentication across all services.
    
    Args:
        credentials: HTTP Bearer token credentials
        
    Returns:
        Admin data dictionary
        
    Raises:
        HTTPException: If authentication fails or user is not an admin
    """
    token = credentials.credentials
    jwt_handler = get_jwt_handler()
    collections = get_collections()
    
    # Verify token
    payload = jwt_handler.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get admin_id from payload
    admin_id = payload.get("sub") or payload.get("admin_id")
    if not admin_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing admin ID",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Find admin in database (supports both ObjectId and email in token subject)
    admins_collection = collections.get_admins_collection()

    admin = None
    # First, try ObjectId-based lookup
    try:
        object_id = ObjectId(admin_id)
        admin = await admins_collection.find_one({"_id": object_id})
    except Exception:
        admin = None

    # Fallback: if not found or not a valid ObjectId, try email-based lookup
    if not admin:
        admin = await admins_collection.find_one({"email": admin_id})
        if not admin:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: invalid admin ID format",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not admin.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin account is deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {
        "admin_id": str(admin["_id"]),
        "user_id": str(admin["_id"]),  # Add user_id for compatibility
        "username": admin.get("username", ""),
        "full_name": admin.get("name", ""),
        "email": admin.get("email", ""),
        "role": admin.get("role", "admin"),
        "permissions": admin.get("permissions", []),
        "is_active": admin.get("is_active", True)
    }

async def get_optional_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))) -> Optional[Dict]:
    """
    Get current user if token is provided, otherwise return None.
    
    This function allows for optional authentication where some endpoints
    can work with or without authentication.
    
    Args:
        credentials: Optional HTTP Bearer token credentials
        
    Returns:
        User data dictionary or None if no token provided
    """
    if not credentials:
        return None
    
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None

# Role-based access control decorators
def require_role(required_role: str):
    """
    Decorator to require specific user role.
    
    Args:
        required_role: Required role (e.g., "Captain", "Member")
        
    Returns:
        Dependency function that checks user role
    """
    async def check_role(current_user: Dict = Depends(get_current_user)):
        if current_user.get("role") != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {required_role}"
            )
        return current_user
    
    return check_role

def require_membership_status(required_status: str):
    """
    Decorator to require specific membership status.
    
    Args:
        required_status: Required membership status (e.g., "active", "trial")
        
    Returns:
        Dependency function that checks membership status
    """
    async def check_membership(current_user: Dict = Depends(get_current_user)):
        if current_user.get("membership_status") != required_status:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required membership status: {required_status}"
            )
        return current_user
    
    return check_membership

def require_admin_permission(required_permission: str):
    """
    Decorator to require specific admin permission.
    
    Args:
        required_permission: Required permission (e.g., "user_management", "club_management")
        
    Returns:
        Dependency function that checks admin permission
    """
    async def check_permission(current_admin: Dict = Depends(get_current_admin)):
        permissions = current_admin.get("permissions", [])
        if required_permission not in permissions and "all" not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required permission: {required_permission}"
            )
        return current_admin
    
    return check_permission
