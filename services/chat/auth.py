import os
import jwt
import logging
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Optional, Tuple
from dotenv import load_dotenv

from .db import (
    get_user_collection,
    get_club_collection,
    get_club_memberships_collection,
    get_user_access_collection,
)
from .models import ChatUser, UserRole, MembershipStatus

# Setup logging
logger = logging.getLogger(__name__)


def create_response(status_code: int, status: str, message: str, data=None):
    """Create a common response body with status code"""
    logger.debug(
        f"Creating API response - Status: {status_code}, Type: {status}, Message: {message}"
    )

    # Use jsonable_encoder to handle datetime and other non-JSON serializable objects
    encoded_data = jsonable_encoder(data) if data is not None else None

    return JSONResponse(
        status_code=status_code,
        content={"status": status, "message": message, "data": encoded_data},
    )


load_dotenv()

# JWT Configuration (should match other services)
SECRET_KEY = os.getenv("JWT_SECRET", "your_super_secret_jwt_key")
ALGORITHM = "HS256"

# Security scheme for JWT authentication
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Get current user from JWT token"""
    token = credentials.credentials
    logger.debug(f"Authenticating user with token: {token[:20]}...")
    try:
        # Decode JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logger.debug(f"Decoded JWT payload for user authentication")
        user_id = payload.get("sub")
        logger.debug(f"Extracted user_id: {user_id}")
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
        "username": user.get("username", user["full_name"].replace(" ", "_").lower()),
    }


async def check_club_access(user_id: str, club_id: str) -> Tuple[bool, dict]:
    """Check if user has access to club chat and return access details"""

    # Get club information by name_based_id
    club_collection = get_club_collection()
    logger.debug(f"Searching for club with name_based_id: {club_id}")
    logger.debug(f"Using database: {club_collection.database.name}")
    logger.debug(f"Using collection: {club_collection.name}")

    try:
        # First try to find club by name_based_id with is_active filter
        club = await club_collection.find_one(
            {"name_based_id": club_id, "is_active": True}
        )
        logger.debug(f"Club found by name_based_id with is_active: {club is not None}")

        if not club:
            # Try without is_active filter to see if club exists
            club = await club_collection.find_one({"name_based_id": club_id})
            logger.debug(
                f"Club found by name_based_id without is_active filter: {club is not None}"
            )

            if club:
                is_active = club.get("is_active", None)
                logger.debug(f"Club exists but is_active: {is_active}")

                # If is_active is not set or is None, consider it active (backward compatibility)
                if is_active is None:
                    logger.debug(
                        f"Club is_active is None, treating as active for backward compatibility"
                    )
                elif is_active is False:
                    logger.warning(f"Club is explicitly set to inactive")
                    return False, {"error": "Club is inactive"}
                # If is_active is True, we already found it in the first query

        if not club:
            # If not found by name_based_id, try ObjectId for backward compatibility
            try:
                club_object_id = ObjectId(club_id)
                club = await club_collection.find_one({"_id": club_object_id})
                logger.debug(f"Club found by ObjectId: {club is not None}")

                if club:
                    is_active = club.get("is_active", None)
                    if is_active is False:
                        logger.warning(f"Club found by ObjectId but is inactive")
                        return False, {"error": "Club is inactive"}
            except Exception as e:
                logger.debug(f"ObjectId search failed: {e}")
                pass

        if not club:
            logger.warning(f"Club not found with name_based_id: {club_id}")
            return False, {"error": "Club not found"}

        logger.debug(
            f"Found club: {club.get('name', 'Unknown')} (ID: {club.get('_id')})"
        )

    except Exception as e:
        logger.error(f"Error finding club: {str(e)}")
        return False, {"error": f"Error finding club: {str(e)}"}

    # Check if user is the captain
    if club["captain_id"] == user_id:
        club_membership_status = club.get("membership_status", "active")
        return True, {
            "role": UserRole.CAPTAIN,
            "membership_status": club_membership_status,
            "membership_type": "captain",
            "club_name": club["name"],
            "member_count": club.get("member_count", 0),
            "is_muted": False,
        }

    # Check if user is a moderator in detailed_moderators list
    detailed_moderators = club.get("detailed_moderators", [])
    for moderator in detailed_moderators:
        if str(moderator.get("user_id")) == str(user_id):
            # Check if moderator is active
            moderator_status = moderator.get("status", "active")
            if moderator_status == "active":
                # Fetch moderator user information from users table
                users_collection = get_user_collection()
                moderator_user = await users_collection.find_one(
                    {"_id": ObjectId(user_id)}
                )

                if not moderator_user:
                    logger.warning(f"Moderator user {user_id} not found in users table")
                    return False, {"error": "Moderator user not found"}

                if not moderator_user.get("is_active", True):
                    logger.warning(f"Moderator user {user_id} is inactive")
                    return False, {"error": "Moderator user is inactive"}

                club_membership_status = club.get("membership_status", "active")
                return True, {
                    "role": UserRole.MODERATOR,
                    "membership_status": club_membership_status,
                    "membership_type": "moderator",
                    "club_name": club["name"],
                    "member_count": club.get("member_count", 0),
                    "is_muted": False,
                }
            else:
                logger.warning(
                    f"Moderator {user_id} found but status is {moderator_status}"
                )
                return False, {"error": f"Moderator status is {moderator_status}"}

    # Check if user has active membership
    memberships_collection = get_club_memberships_collection()
    logger.debug(f"Checking membership for user: {user_id}, club: {str(club['_id'])}")
    logger.debug(f"Using memberships database: {memberships_collection.database.name}")

    # Try different membership status values for broader compatibility
    membership = await memberships_collection.find_one(
        {
            "user_id": user_id,
            "club_id": str(club["_id"]),  # Use actual club ObjectId
            "subscription_status": {"$in": ["active", "trial", "paid", "subscribed"]},
        }
    )

    logger.debug(f"Membership found with active status: {membership is not None}")
    if membership:
        logger.debug(f"Membership status: {membership.get('subscription_status')}")
        logger.debug(f"Is trial: {membership.get('is_trial_membership', False)}")
    else:
        # Let's check if there's any membership record at all
        any_membership = await memberships_collection.find_one(
            {"user_id": user_id, "club_id": str(club["_id"])}
        )
        if any_membership:
            logger.debug(
                f"Found membership but status: {any_membership.get('subscription_status')}"
            )
            logger.debug(f"Membership details: {any_membership}")

            # If membership exists but status is not in our list, check if it's valid
            status = any_membership.get("subscription_status", "")
            if status in ["pending", "cancelled", "expired"]:
                logger.warning(f"Membership status is {status}, denying access")
                return False, {"error": f"Membership status is {status}"}
            else:
                logger.debug(
                    f"Unknown membership status '{status}', treating as active"
                )
                membership = any_membership
        else:
            # Check if user is in the club's members array (alternative membership check)
            logger.debug(f"Checking club members array...")
            club_members = club.get("members", [])
            logger.debug(f"Club has {len(club_members)} members")

            user_in_members = False
            for member in club_members:
                if str(member.get("user_id")) == str(user_id):
                    user_in_members = True
                    logger.debug(f"User found in club members array")
                    break

            if user_in_members:
                logger.debug(
                    f"User is in club members array, treating as active membership"
                )
                # Create a mock membership object for users in the members array
                membership = {
                    "user_id": user_id,
                    "club_id": str(club["_id"]),
                    "subscription_status": "active",
                    "is_trial_membership": False,
                }
            else:
                # Check if user is in the club's paid_members array
                logger.debug(f"Checking club paid_members array...")
                club_paid_members = club.get("paid_members", [])
                logger.debug(f"Club has {len(club_paid_members)} paid members")

                user_in_paid_members = False
                for member in club_paid_members:
                    if str(member.get("user_id")) == str(user_id):
                        user_in_paid_members = True
                        logger.debug(f"User found in club paid_members array")
                        break

                if user_in_paid_members:
                    logger.debug(
                        f"User is in club paid_members array, treating as active paid membership"
                    )
                    # Create a mock membership object for users in the paid_members array
                    membership = {
                        "user_id": user_id,
                        "club_id": str(club["_id"]),
                        "subscription_status": "paid",
                        "is_trial_membership": False,
                    }
                else:
                    logger.warning(
                        f"No membership record found for user {user_id} in club {str(club['_id'])}"
                    )
                    return False, {"error": "No active membership found"}

    if not membership:
        return False, {"error": "No active membership found"}

    # Check if membership is expired
    now = datetime.utcnow()
    if membership.get("expires_date") and membership["expires_date"] < now:
        return False, {"error": "Membership has expired"}

    # Get membership_status from club data (active/inactive)
    club_membership_status = club.get("membership_status", "active")
    membership_status = club_membership_status  # Use club's membership_status directly

    # Determine membership type based on club data and membership details
    membership_type = "member"  # Default to member

    # Check if user is a moderator (if moderators field exists in club)
    if "moderators" in club:
        moderators = club.get("moderators", [])
        for moderator in moderators:
            if str(moderator.get("user_id")) == str(user_id):
                membership_type = "moderator"
                break

    # Check if it's a trial membership based on membership record
    is_trial = membership.get("is_trial_membership", False)
    if is_trial:
        membership_type = "trial_member"
    elif membership.get("subscription_status") == "paid":
        membership_type = "paid_member"

    logger.debug(f"Club membership_status: {club_membership_status}")
    logger.debug(f"Determined membership_type: {membership_type}")

    # Check for mute status
    user_access_collection = get_user_access_collection()
    access_record = await user_access_collection.find_one(
        {
            "user_id": user_id,
            "club_id": club_id,  # Use the name_based_id (club_id parameter)
        }
    )

    is_muted = False
    if access_record:
        is_muted = access_record.get("is_muted", False)

        # Check if mute has expired
        if is_muted and access_record.get("muted_until"):
            if access_record["muted_until"] < now:
                # Unmute user automatically
                await user_access_collection.update_one(
                    {"_id": access_record["_id"]},
                    {
                        "$set": {
                            "is_muted": False,
                            "muted_until": None,
                            "updated_at": now,
                        }
                    },
                )
                is_muted = False

    return True, {
        "role": UserRole.MEMBER,
        "membership_status": membership_status,
        "membership_type": membership_type,
        "club_name": club["name"],
        "member_count": club.get("member_count", 0),
        "is_muted": is_muted,
    }


async def get_chat_user(user_data: dict, club_id: str) -> ChatUser:
    """Convert user data to ChatUser with club-specific information"""

    # Check access and get club-specific details
    has_access, access_details = await check_club_access(user_data["user_id"], club_id)

    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=access_details.get("error", "Access denied"),
        )

    from .models import UserRole, MembershipStatus

    # Convert string values to enum values
    role_enum = (
        UserRole(access_details["role"])
        if isinstance(access_details["role"], str)
        else access_details["role"]
    )
    membership_status_enum = (
        MembershipStatus(access_details["membership_status"])
        if isinstance(access_details["membership_status"], str)
        else access_details["membership_status"]
    )

    return ChatUser(
        user_id=user_data["user_id"],
        username=user_data["username"],
        full_name=user_data["full_name"],
        avatar_url=user_data.get("avatar_url"),
        role=role_enum,
        membership_status=membership_status_enum,
        is_muted=access_details.get("is_muted", False),
    )


async def check_locker_room_access(
    club_id: str, current_user: dict = Depends(get_current_user)
):
    """Check and return detailed locker room access information"""

    try:
        user_id = current_user["user_id"]
        logger.info(f"Checking locker room access for user {user_id} in club {club_id}")

        has_access, access_details = await check_club_access(user_id, club_id)

        if not has_access:
            error_message = access_details.get("error", "Access denied")
            logger.warning(
                f"Access denied for user {user_id} in club {club_id}: {error_message}"
            )

            return create_response(
                status_code=status.HTTP_403_FORBIDDEN,
                status="error",
                message=error_message,
                data={
                    "has_access": False,
                    "club_name": "Unknown",
                    "member_count": 0,
                    "restrictions": [error_message],
                },
            )

        restrictions = []
        if access_details.get("is_muted"):
            restrictions.append("User is muted and cannot send messages")

        access_data = {
            "has_access": True,
            "user_role": access_details["role"],
            "membership_status": access_details["membership_status"],
            "is_muted": access_details.get("is_muted", False),
            "club_name": access_details["club_name"],
            "member_count": access_details["member_count"],
            "restrictions": restrictions,
        }

        logger.info(f"Access granted for user {user_id} in club {club_id}")

        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Locker room access information retrieved successfully",
            data=access_data,
        )

    except HTTPException as e:
        logger.warning(f"HTTP error checking locker room access: {e.detail}")
        return create_response(e.status_code, "error", e.detail, None)
    except Exception as e:
        logger.error(f"Error checking locker room access: {e}")
        return create_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to check locker room access: {str(e)}",
            data=None,
        )


async def require_chat_access(
    club_id: str, current_user: dict = Depends(get_current_user)
) -> ChatUser:
    """Dependency that requires chat access and returns ChatUser"""

    chat_user = await get_chat_user(current_user, club_id)
    return chat_user


async def require_moderator_access(
    club_id: str, current_user: dict = Depends(get_current_user)
) -> ChatUser:
    """Dependency that requires moderator or captain access"""

    chat_user = await get_chat_user(current_user, club_id)

    if chat_user.role not in [UserRole.CAPTAIN, UserRole.MODERATOR]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Moderator or captain access required",
        )

    return chat_user


async def require_unmuted_access(
    club_id: str, current_user: dict = Depends(get_current_user)
) -> ChatUser:
    """Dependency that requires unmuted chat access"""

    chat_user = await get_chat_user(current_user, club_id)

    if chat_user.is_muted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot send messages while muted",
        )

    return chat_user


async def update_user_access_record(
    user_id: str, club_id: str, role: UserRole, membership_status: MembershipStatus
):
    """Update or create user access record"""
    user_access_collection = get_user_access_collection()
    now = datetime.utcnow()

    # Upsert user access record
    await user_access_collection.update_one(
        {"user_id": user_id, "club_id": club_id},
        {
            "$set": {
                "role": role.value,
                "membership_status": membership_status.value,
                "last_seen": now,
                "updated_at": now,
            },
            "$setOnInsert": {"is_muted": False, "joined_at": now},
        },
        upsert=True,
    )


async def mute_user(
    user_id: str,
    club_id: str,
    muted_by: str,
    reason: Optional[str] = None,
    duration_hours: Optional[int] = None,
) -> bool:
    """Mute a user in a specific club"""
    user_access_collection = get_user_access_collection()
    now = datetime.utcnow()

    # Calculate mute expiration
    muted_until = None
    if duration_hours:
        muted_until = now + timedelta(hours=duration_hours)

    result = await user_access_collection.update_one(
        {"user_id": user_id, "club_id": club_id},
        {
            "$set": {
                "is_muted": True,
                "muted_until": muted_until,
                "muted_by": muted_by,
                "muted_reason": reason,
                "updated_at": now,
            }
        },
        upsert=True,
    )

    return result.modified_count > 0 or result.upserted_id is not None


async def unmute_user(user_id: str, club_id: str) -> bool:
    """Unmute a user in a specific club"""
    user_access_collection = get_user_access_collection()
    now = datetime.utcnow()

    result = await user_access_collection.update_one(
        {"user_id": user_id, "club_id": club_id},
        {
            "$set": {
                "is_muted": False,
                "muted_until": None,
                "muted_by": None,
                "muted_reason": None,
                "updated_at": now,
            }
        },
    )

    return result.modified_count > 0


# Optional authentication for Socket.IO (moved to core/socket)
async def authenticate_socket_user(token: str) -> Optional[dict]:
    """Authenticate user from Socket.IO token (moved to core/socket)"""
    if not token:
        return None

    try:
        # Remove 'Bearer ' prefix if present
        if token.startswith("Bearer "):
            token = token[7:]

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")

        if not user_id:
            return None

        # Get user from database
        users_collection = get_user_collection()
        user = await users_collection.find_one({"_id": ObjectId(user_id)})

        if not user or not user.get("is_active", True):
            return None

        return {
            "user_id": str(user["_id"]),
            "full_name": user["full_name"],
            "email": user["email"],
            "role": user["role"],
            "avatar_url": user.get("avatar_url"),
            "membership_status": user.get("membership_status", "none"),
            "username": user.get(
                "username", user["full_name"].replace(" ", "_").lower()
            ),
        }

    except Exception:
        return None
