import jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId
from .db import get_user_collection
import os
from dotenv import load_dotenv

load_dotenv()

# JWT Configuration (should match auth service)
SECRET_KEY = os.getenv('SECRET_KEY', 'your_super_secret_jwt_key')
ALGORITHM = "HS256"

# Security scheme for JWT authentication
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Get current user from JWT token"""
    token = credentials.credentials
    
    try:
        # Decode JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user from database
    users_collection = get_user_collection()
    
    try:
        object_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: invalid user ID format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Find user in database
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
    
    return {
        "user_id": str(user["_id"]),
        "full_name": user["full_name"],
        "email": user["email"],
        "phone": user.get("phone"),
        "role": user["role"],
        "avatar_url": user.get("avatar_url"),
        "membership_status": user.get("membership_status", "none"),
        "membership_type": user.get("membership_type", "none"),
        "subscription_id": user.get("subscription_id"),
        "stripe_customer_id": user.get("stripe_customer_id")
    }

async def get_current_captain(current_user: dict = Depends(get_current_user)) -> dict:
    """Verify user is a captain with active paid or trial membership"""
    
    # Check if user has Captain role
    if current_user["role"] != "Captain":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only captains can create clubs"
        )
    
    # Check if captain has active membership
    membership_status = current_user.get("membership_status", "none")
    if membership_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Captain must have an active membership to create clubs"
        )
    
    # Check if captain has paid or trial membership type
    membership_type = current_user.get("membership_type", "none")
    if membership_type not in ["paid", "trial"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Captain must have a paid or trial membership to create clubs"
        )
    
    return current_user

async def get_current_captain_optional(current_user: dict = Depends(get_current_user)) -> dict:
    """Get current captain if user is a captain, otherwise just return user"""
    # This is for endpoints where captains might have additional privileges
    # but regular users can also access
    return current_user

async def get_current_user_or_captain(current_user: dict = Depends(get_current_user)) -> dict:
    """Get current user (captain or member) with active membership for hub access"""
    
    # Temporarily make membership check more lenient for debugging
    # Check if user has active membership (required for hub access)
    membership_status = current_user.get("membership_status", "none")
    membership_type = current_user.get("membership_type", "none")
    
    # Log the membership details for debugging
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"User membership check: status={membership_status}, type={membership_type}, role={current_user.get('role')}")
    
    # For now, allow access if user is a Captain regardless of membership status
    if current_user.get("role") == "Captain":
        logger.info("Allowing Captain access regardless of membership status for debugging")
        return current_user
    
    # For non-captains, still check membership
    if membership_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User must have an active membership to access hub content (current: {membership_status})"
        )
    
    if membership_type not in ["paid", "trial", "free"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User must have a paid or trial membership to access hub content (current: {membership_type})"
        )
    
    return current_user

def verify_club_ownership(club_captain_id: str, current_user: dict) -> bool:
    """Verify if current user owns the club"""
    return club_captain_id == current_user["user_id"]

async def get_club_owner(current_user: dict = Depends(get_current_user)) -> dict:
    """Verify user is a captain and can modify clubs"""
    if current_user["role"] != "Captain":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only captains can modify clubs"
        )
    
    return current_user

class ClubOwnershipChecker:
    """Dependency class to check club ownership"""
    def __init__(self, club_id: str):
        self.club_id = club_id
    
    async def __call__(self, current_user: dict = Depends(get_current_user)):
        from .db import get_club_collection
        
        # Get club from database
        club_collection = get_club_collection()
        try:
            club_object_id = ObjectId(self.club_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid club ID format"
            )
        
        club = await club_collection.find_one({"_id": club_object_id})
        
        if not club:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Club not found"
            )
        
        # Check ownership
        if not verify_club_ownership(club["captain_id"], current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only modify your own clubs"
            )
        
        return current_user 