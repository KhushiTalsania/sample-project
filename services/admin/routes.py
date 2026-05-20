import os
import bcrypt

import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request, Depends, Query, Form, UploadFile, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT, HTTP_403_FORBIDDEN, HTTP_500_INTERNAL_SERVER_ERROR
from bson import ObjectId
from .db import admin_collection, sessions_collection, reset_tokens_collection
from .models import (
    AdminIn, AdminResponse, UserListRequest, UserResponse, UserListResponse, 
    AddUserRequest, EditUserRequest, UserStatus, UserRole, SortField, SortOrder,
    AddUserResponse, EditUserResponse, DeleteUserResponse,
    UserSearchRequest, UserSearchResponse, UserExportRequest, UserExportResponse,ImageUploadResponse,
    AdminDeletionRequest, AdminDeletionResponse, AdminReactivationRequest, AdminReactivationResponse,
    AdminDeletionUserRole, AdminDeletionType
)
from .users_service import admin_users_service
from typing import Dict, Optional, List
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from core.utils.email_service import get_email_service  # Use centralized email service
from .clubs_service import admin_clubs_service
from .moderators_service import admin_moderators_service
from .club_management_service import admin_club_management_service
from .admin_deletion_service import admin_deletion_service
from .moderator_details_service import admin_moderator_details_service
from .moderator_management_service import admin_moderator_management_service
from .captain_request_service import admin_captain_request_service
from .subscription_plans_service import admin_subscription_plans_service
from .inclusions_service import admin_inclusions_service
from .sports_service import admin_sports_service
from .admin_statistics_service import get_admin_statistics_service
from .models import (
    ClubListRequest, ClubSortField, ClubStatus, SortOrder,
    ClubStatusUpdateRequest, ClubAnalyticsRequest, ClubBulkActionRequest,
    ClubAdvancedSearchRequest, ClubAdvancedSearchResponse, ClubSearchSortField,
    ClubCreateRequest, ClubUpdateRequest, ClubCreateResponse, ClubUpdateResponse,
    ClubDeleteResponse, ClubType, ModeratorListRequest, ModeratorListResponse,
    ModeratorStatus, ClubApprovalRequest, ClubApprovalResponse, ClubApprovalStatus, ClubMonitoringResponse,
    ClubPicksRequest, ClubPicksResponse, ActivityPeriod, ModeratorDetailsResponse,
    ModeratorCreateRequest, ModeratorUpdateRequest, ModeratorDeleteRequest,
    ModeratorCreateResponse, ModeratorUpdateResponse, ModeratorDeleteResponse,
    CaptainModeratorRequestSubmission, CaptainRequestSubmissionResponse,
    AdminRequestApprovalRequest, AdminRequestApprovalResponse,
    CaptainRequestListRequest, CaptainRequestListResponse,
    ClubUpdateDetailsRequest,
    # Subscription Plans Models
    SubscriptionPlanListRequest, SubscriptionPlanListResponse,
    SubscriptionPlanCSVExportRequest, SubscriptionPlanCSVExportResponse,
    SubscriptionPlanStatusUpdateRequest, SubscriptionPlanStatusUpdateResponse,
    SubscriptionPlanDeleteResponse,
    # Inclusions and Sports Models
    InclusionCreateRequest, InclusionResponse, InclusionUpdateRequest, InclusionListResponse,
    SportCreateRequest, SportResponse, SportUpdateRequest, SportListResponse
)

# Settings
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
SECRET_KEY = JWT_SECRET  # Alias for consistency
ALGORITHM = JWT_ALGORITHM  # Alias for consistency
RESET_SECRET = os.getenv("RESET_TOKEN_SECRET")
RESET_SALT = "password-reset-salt"
reset_serializer = URLSafeTimedSerializer(RESET_SECRET)

# Security scheme for Bearer token
security_scheme = HTTPBearer(
    scheme_name="Bearer",
    description="Enter your JWT access token. Example: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0akBtYWlsaW5hdG9yLmNvbSIsImV4cCI6MTc1ODg2NTk5OC4wOTMyNzF9.gQSCsVoIu5vIyLLDtGCMeVAX_9g4ckpYYQ5_CXc8gwU"
)

router = APIRouter(prefix="/api/admin")

# Include admin user control router
from . import admin_user_control
router.include_router(admin_user_control.router)

# Helper functions
def create_access_token(data: Dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.now(tz=timezone.utc) + expires_delta
    to_encode.update({"exp": expire.timestamp()})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def create_response(status_code: int, status: str, message: str, data=None):
    """Create a common response body with status code"""
    print(f"Creating API response - Status: {status_code}, Type: {status}, Message: {message}")
    
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={"status": status, "message": message, "data": data},
    )

async def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    """Get current admin from JWT token in Authorization header"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(HTTP_401_UNAUTHORIZED, "Invalid token")
        
        # Verify the session exists
        session = await sessions_collection.find_one({"token": token, "email": email})
        if not session:
            raise HTTPException(HTTP_401_UNAUTHORIZED, "Session invalidated or expired")
        
        # Ensure session has last_active field
        if "last_active" not in session:
            # If no last_active field, create one and continue
            await sessions_collection.update_one(
                {"_id": session["_id"]},
                {"$set": {"last_active": datetime.now(tz=timezone.utc)}}
            )
            return {"user_id": email, "email": email}

        # Check inactivity expiry (30 days)
        last_active = session["last_active"]
        # Ensure last_active is timezone-aware, if not, assume UTC
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)
            print(f"Converted timezone-naive timestamp to UTC for session {session['_id']}")
        
        # Calculate time difference safely
        try:
            time_diff = datetime.now(tz=timezone.utc) - last_active
            if time_diff > timedelta(days=30):
                print(f"Session expired for {email}, time difference: {time_diff}")
                await sessions_collection.delete_one({"_id": session["_id"]})
                raise HTTPException(HTTP_401_UNAUTHORIZED, "Session expired due to inactivity")
        except Exception as e:
            print(f"Error calculating session expiry for {email}: {e}")
            # If there's an error with time calculation, invalidate the session
            await sessions_collection.delete_one({"_id": session["_id"]})
            raise HTTPException(HTTP_401_UNAUTHORIZED, "Session validation error")

        # Update session last active time
        await sessions_collection.update_one({"_id": session["_id"]}, {"$set": {"last_active": datetime.now(tz=timezone.utc)}})
        return {"user_id": email, "email": email}
    except jwt.PyJWTError:
        raise HTTPException(HTTP_401_UNAUTHORIZED, "Invalid authentication or token expired")

async def cleanup_old_reset_tokens():
    """Clean up old invalidated reset tokens (older than 24 hours)"""
    try:
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        result = await reset_tokens_collection.delete_many({
            "invalidated": True,
            "used_at": {"$lt": cutoff_time}
        })
        if result.deleted_count > 0:
            print(f"Cleaned up {result.deleted_count} old reset tokens")
    except Exception as e:
        print(f"Error cleaning up old reset tokens: {e}")

async def migrate_sessions_timezone():
    """Migrate existing sessions to use timezone-aware timestamps"""
    try:
        # Find all sessions with timezone-naive timestamps
        naive_sessions = await sessions_collection.find({
            "last_active": {"$exists": True}
        }).to_list(length=None)
        
        updated_count = 0
        for session in naive_sessions:
            last_active = session.get("last_active")
            if last_active and last_active.tzinfo is None:
                # Update to timezone-aware timestamp
                await sessions_collection.update_one(
                    {"_id": session["_id"]},
                    {"$set": {"last_active": last_active.replace(tzinfo=timezone.utc)}}
                )
                updated_count += 1
        
        if updated_count > 0:
            print(f"Migrated {updated_count} sessions to timezone-aware timestamps")
    except Exception as e:
        print(f"Error migrating sessions timezone: {e}")

def get_client_ip(request: Request) -> Optional[str]:
    """Get client IP address"""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None

class LoginRequest(AdminIn):
    pass

# Routes

@router.post("/login")
async def login(data: LoginRequest):
    # Removed timezone migration for performance
    admin = await admin_collection.find_one({"email": data.email})
    print(admin,"admin")
    if not admin or not bcrypt.checkpw(data.password.encode(), admin["password_hash"].encode()):
        return create_response(
            status_code=HTTP_401_UNAUTHORIZED,
            status="error",
            message="Invalid credentials",
            data=None
        )

    # Generate the JWT token
    token = create_access_token({"sub": data.email}, timedelta(days=30))

    # Save session
    await sessions_collection.insert_one({
        "email": data.email,
        "token": token,
        "last_active": datetime.now(tz=timezone.utc)
    })
    
    return create_response(
        status_code=200,
        status="success",
        message="Login successful",
        data={
            "access_token": token, 
            "token_type": "bearer",
            "name": admin.get("name", "Admin"),
            "avatar_url": admin.get("avatar_url"),
            "role": admin.get("role", "Admin")
        }
    )

@router.post("/logout")
async def logout(token: str = Depends(get_current_admin)):
    # Invalidate the session
    await sessions_collection.delete_one({"token": token})
    return create_response(
        status_code=200,
        status="success",
        message="Logged out successfully",
        data=None
    )

@router.get("/profile")
async def get_admin_profile(token: str = Depends(get_current_admin)):
    """Get current admin profile information"""
    try:
        # Extract email from token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        
        if not email:
            return create_response(
                status_code=HTTP_401_UNAUTHORIZED,
                status="error",
                message="Invalid token",
                data=None
            )
        
        # Get admin data
        admin = await admin_collection.find_one({"email": email})
        if not admin:
            return create_response(
                status_code=HTTP_404_NOT_FOUND,
                status="error",
                message="Admin not found",
                data=None
            )
        
        return create_response(
            status_code=200,
            status="success",
            message="Profile retrieved successfully",
            data={
                "email": admin.get("email"),
                "name": admin.get("name", "Admin"),
                "avatar_url": admin.get("avatar_url"),
                "role": admin.get("role", "Admin")
            }
        )
        
    except jwt.ExpiredSignatureError:
        return create_response(
            status_code=HTTP_401_UNAUTHORIZED,
            status="error",
            message="Token expired",
            data=None
        )
    except jwt.JWTError:
        return create_response(
            status_code=HTTP_401_UNAUTHORIZED,
            status="error",
            message="Invalid token",
            data=None
        )
    except Exception as e:
        print(f"Error in get_admin_profile: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to get profile: {str(e)}",
            data=None
        )

class AdminProfileUpdateRequest(BaseModel):
    """Request model for updating admin profile"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Admin name")
    avatar_url: Optional[str] = Field(None, description="URL to admin avatar")

@router.put("/profile")
async def update_admin_profile(
    profile_data: AdminProfileUpdateRequest,
    token: str = Depends(get_current_admin)
):
    """Update current admin profile information"""
    try:
        # Extract email from token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        
        if not email:
            return create_response(
                status_code=HTTP_401_UNAUTHORIZED,
                status="error",
                message="Invalid token",
                data=None
            )
        
        # Build update document
        update_doc = {}
        if profile_data.name is not None:
            update_doc["name"] = profile_data.name
        if profile_data.avatar_url is not None:
            update_doc["avatar_url"] = profile_data.avatar_url
        
        if not update_doc:
            return create_response(
                status_code=HTTP_400_BAD_REQUEST,
                status="error",
                message="No fields to update",
                data=None
            )
        
        # Update admin profile
        result = await admin_collection.update_one(
            {"email": email},
            {"$set": update_doc}
        )
        
        if result.modified_count > 0:
            # Get updated admin data
            updated_admin = await admin_collection.find_one({"email": email})
            return create_response(
                status_code=200,
                status="success",
                message="Profile updated successfully",
                data={
                    "email": updated_admin.get("email"),
                    "name": updated_admin.get("name", "Admin"),
                    "avatar_url": updated_admin.get("avatar_url"),
                    "role": updated_admin.get("role", "Admin")
                }
            )
        else:
            return create_response(
                status_code=200,
                status="success",
                message="No changes made to profile",
                data=None
            )
        
    except jwt.ExpiredSignatureError:
        return create_response(
            status_code=HTTP_401_UNAUTHORIZED,
            status="error",
            message="Token expired",
            data=None
        )
    except jwt.JWTError:
        return create_response(
            status_code=HTTP_401_UNAUTHORIZED,
            status="error",
            message="Invalid token",
            data=None
        )
    except Exception as e:
        print(f"Error in update_admin_profile: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to update profile: {str(e)}",
            data=None
        )

class ForgotPasswordRequest(BaseModel):
    email: str

@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, request: Request):
    admin = await admin_collection.find_one({"email": data.email})
    if not admin:
        return create_response(
            status_code=200,
            status="success",
            message="If email exists, reset link sent",
            data=None
        )

    # Generate reset token
    token = reset_serializer.dumps(data.email, salt=RESET_SALT)
    # Construct reset link
    reset_link = f"http://45.79.111.106:5016/reset-password?token={token}"

    # Send reset email
    subject = "Admin Panel Password Reset"
    body = f"""
Hello,

You requested to reset your password. Click the link below to reset it. This link will expire in 15 minutes:

{reset_link}

If you did not request this, please ignore this email.

Thanks,
Admin Panel Team
"""
    email_service = get_email_service()
    await email_service.send_email(data.email, subject, body)
    return create_response(
        status_code=200,
        status="success",
        message="If email exists, reset link sent",
        data=None
    )

class ResetPasswordRequest(BaseModel):
    password: str

@router.post("/reset-password")
async def reset_password(token: str = Query(..., description="Reset token"), data: ResetPasswordRequest = None):
    try:
        # Decode and validate reset token
        email = reset_serializer.loads(token, salt=RESET_SALT, max_age=900)
    except SignatureExpired:
        return create_response(
            status_code=HTTP_401_UNAUTHORIZED,
            status="error",
            message="Reset token expired",
            data=None
        )
    except BadSignature:
        return create_response(
            status_code=HTTP_401_UNAUTHORIZED,
            status="error",
            message="Invalid reset token",
            data=None
        )

    # Hash new password and update it
    pw_hash = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    await admin_collection.update_one({"email": email}, {"$set": {"password_hash": pw_hash}})
    
    # Store the used token to invalidate it
    await reset_tokens_collection.insert_one({
        "token": token,
        "email": email,
        "used_at": datetime.now(tz=timezone.utc),
        "invalidated": True
    })
    
    # Clean up old invalidated tokens
    await cleanup_old_reset_tokens()
    
    # Invalidate all sessions for that admin
    await sessions_collection.delete_many({"email": email})
    return create_response(
        status_code=200,
        status="success",
        message="Password reset successful",
        data=None
    )

# @router.get("/auth/verify-reset-token")
# async def verify_reset_token(token: str = Query(..., description="Reset token to verify")):
#     """
#     Verify if a password reset token is valid
    
#     **Features:**
#     - **Token Validation**: Checks if reset token is valid and not expired
#     - **No Authentication Required**: Public endpoint for token verification
#     - **Security**: Only verifies token validity, doesn't reset password
    
#     **Query Parameters:**
#     - `token`: The reset token to verify
    
#     **Response includes:**
#     - Token validity status
#     - Associated email if token is valid
#     - Expiration information
    
#     **Use Cases:**
#     - Frontend validation before showing password reset form
#     - Check token status before user attempts password reset
#     - Verify token before redirecting to reset page
    
#     **Example Usage:**
#     ```
#     # Verify reset token
#     GET /admin/auth/verify-reset-token?token=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
#     ```
    
#     **Security Note:** This endpoint only verifies token validity and doesn't
#     perform any password changes. It's safe to call without authentication.
#     """
#     try:
#         # Decode and validate reset token
#         email = reset_serializer.loads(token, salt=RESET_SALT, max_age=900)
        
#         # Check if admin exists with this email
#         admin = await admin_collection.find_one({"email": email})
#         if not admin:
#             return create_response(
#                 status_code=HTTP_400_BAD_REQUEST,
#                 status="error",
#                 message="Invalid reset token - admin not found",
#                 data=None
#             )
        
#         # Token is valid and admin exists
#         return create_response(
#             status_code=200,
#             status="success",
#             message="Reset token is valid",
#             data={
#                 "email": email,
#                 "token_valid": True,
#                 "expires_in_seconds": 900,  # 15 minutes
#                 "admin_exists": True
#             }
#         )
        
#     except SignatureExpired:
#         return create_response(
#             status_code=HTTP_401_UNAUTHORIZED,
#             status="error",
#             message="Reset token has expired",
#             data={
#                 "token_valid": False,
#                 "error_type": "expired",
#                 "expires_in_seconds": 0
#             }
#         )
#     except BadSignature:
#         return create_response(
#             status_code=HTTP_400_BAD_REQUEST,
#             status="error",
#             message="Invalid reset token",
#             data={
#                 "token_valid": False,
#                 "error_type": "invalid",
#                 "expires_in_seconds": 0
#             }
#         )
#     except Exception as e:
#         print(f"Error in verify_reset_token: {e}")
#         return create_response(
#             status_code=HTTP_500_INTERNAL_SERVER_ERROR,
#             status="error",
#             message="Error verifying reset token",
#             data={
#                 "token_valid": False,
#                 "error_type": "server_error",
#                 "expires_in_seconds": 0
#             }
#         )


from itsdangerous import SignatureExpired, BadSignature
from datetime import datetime, timedelta, timezone

@router.get("/auth/verify-reset-token")
async def verify_reset_token(token: str = Query(..., description="Reset token to verify")):
    """
    Verify if a password reset token is valid
    """
    try:
        # Check if token has been used/invalidated
        used_token = await reset_tokens_collection.find_one({"token": token, "invalidated": True})
        if used_token:
            return create_response(
                status_code=HTTP_401_UNAUTHORIZED,
                status="error",
                message="Reset token has already been used",
                data={
                    "token_valid": False,
                    "error_type": "already_used",
                    "expires_in_seconds": 0
                }
            )

        # Get email and timestamp
        email, timestamp = reset_serializer.loads(
            token,
            salt=RESET_SALT,
            max_age=900,
            return_timestamp=True
        )

        # `timestamp` is already a datetime object
        token_time = timestamp
        now = datetime.now(tz=timezone.utc)
        elapsed = (now - token_time).total_seconds()
        expires_in = max(0, 900 - int(elapsed))

        # Check if admin exists with this email
        admin = await admin_collection.find_one({"email": email})
        if not admin:
            return create_response(
                status_code=HTTP_400_BAD_REQUEST,
                status="error",
                message="Invalid reset token - admin not found",
                data=None
            )

        # Return dynamic expiry
        return create_response(
            status_code=200,
            status="success",
            message="Reset token is valid",
            data={
                "email": email,
                "token_valid": True,
                "expires_in_seconds": expires_in,
                "admin_exists": True
            }
        )

    except SignatureExpired:
        return create_response(
            status_code=HTTP_401_UNAUTHORIZED,
            status="error",
            message="Reset token has expired",
            data={
                "token_valid": False,
                "error_type": "expired",
                "expires_in_seconds": 0
            }
        )
    except BadSignature:
        return create_response(
            status_code=HTTP_400_BAD_REQUEST,
            status="error",
            message="Invalid reset token",
            data={
                "token_valid": False,
                "error_type": "invalid",
                "expires_in_seconds": 0
            }
        )
    except Exception as e:
        print(f"Error in verify_reset_token: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message="Error verifying reset token",
            data={
                "token_valid": False,
                "error_type": "server_error",
                "expires_in_seconds": 0
            }
        )


@router.get("/me")
async def get_me(current_admin: dict = Depends(get_current_admin)):
    # Extract email from the current_admin dictionary
    email = current_admin.get("email")
    
    # Fetch admin document using the email
    admin = await admin_collection.find_one({"email": email})
    
    if not admin:
        return create_response(
            status_code=404,
            status="error",
            message="Admin not found",
            data=None
        )

    return create_response(
        status_code=200,
        status="success",
        message="Admin profile retrieved successfully",
        data={
            "email": admin.get("email"),
            "name": admin.get("name"),
            "avatar_url": admin.get("avatar_url"),
            "role": admin.get("role")
        }
    )

# Admin Users Routes

# @router.get("/users/search")
# async def search_users(
#     name: Optional[str] = Query(None, description="Partial or full name of the user"),
#     email: Optional[str] = Query(None, description="Partial or full email of the user"),
#     status: Optional[str] = Query(None, description="Filter by status: active, inactive, banned, deleted"),
#     date_from: Optional[datetime] = Query(None, description="Filter users joined on/after this date"),
#     date_to: Optional[datetime] = Query(None, description="Filter users joined on/before this date"),
#     page: int = Query(1, ge=1, description="Page number (default: 1)"),
#     limit: int = Query(20, ge=1, le=100, description="Items per page (default: 20)"),
#     sort_by: Optional[str] = Query("date_joined", description="Field to sort by: name, date_joined, email, status"),
#     sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
#     admin_request: Request = None,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Advanced search users with comprehensive filtering.
#     Admin-only access with performance optimization for large datasets.
#     """
#     try:
#         # Validate sort_by parameter
#         valid_sort_fields = ["name", "date_joined", "email", "status"]
#         if sort_by not in valid_sort_fields:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid sort_by. Must be one of: {valid_sort_fields}")
        
#         # Validate sort_order parameter
#         valid_sort_orders = ["asc", "desc"]
#         if sort_order not in valid_sort_orders:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid sort_order. Must be one of: {valid_sort_orders}")
        
#         # Validate status parameter
#         valid_statuses = ["active", "inactive", "banned", "deleted"]
#         if status and status not in valid_statuses:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid status. Must be one of: {valid_statuses}")
        
#         # Validate date range
#         if date_from and date_to and date_to < date_from:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "date_to must be after date_from")
        
#         # Convert string values to enums
#         status_enum = None
#         if status:
#             if status == "active":
#                 status_enum = UserStatus.ACTIVE
#             elif status == "inactive":
#                 status_enum = UserStatus.INACTIVE
#             elif status == "banned":
#                 status_enum = UserStatus.BANNED
        
#         sort_field_enum = None
#         if sort_by == "name":
#             sort_field_enum = SortField.NAME
#         elif sort_by == "date_joined":
#             sort_field_enum = SortField.DATE_JOINED
#         elif sort_by == "email":
#             sort_field_enum = SortField.EMAIL
#         elif sort_by == "status":
#             sort_field_enum = SortField.STATUS
        
#         sort_order_enum = SortOrder.ASC if sort_order == "asc" else SortOrder.DESC
        
#         # Get client IP for logging
#         ip_address = get_client_ip(admin_request)
        
#         # Create search request model
#         search_request = UserSearchRequest(
#             name=name,
#             email=email,
#             status=status_enum,
#             date_from=date_from,
#             date_to=date_to,
#             page=page,
#             limit=limit,
#             sort_by=sort_field_enum,
#             sort_order=sort_order_enum
#         )
        
#         # Perform search through service
#         result = await admin_users_service.search_users(search_request, token, ip_address)
        
#         return result
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"Error in search_users: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error performing search: {str(e)}")

# @router.get("/search-logs")
# async def get_search_logs(
#     admin_email: Optional[str] = Query(None, description="Filter by admin email"),
#     limit: int = Query(50, ge=1, le=100, description="Number of search logs to return"),
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get search logs for analytics and monitoring.
#     Admin-only access.
#     """
#     try:
#         logs = await admin_users_service.get_search_logs(admin_email, limit)
        
#         return {
#             "success": True,
#             "message": "Search logs retrieved successfully",
#             "logs": logs,
#             "count": len(logs)
#         }
        
#     except Exception as e:
#         print(f"Error in get_search_logs: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving search logs: {str(e)}")

# @router.get("/users/export")
# async def export_users(
#     name: Optional[str] = Query(None, description="Partial or full name of the user"),
#     email: Optional[str] = Query(None, description="Partial or full email of the user"),
#     status: Optional[str] = Query(None, description="Filter by status: active, inactive, banned, deleted"),
#     date_from: Optional[datetime] = Query(None, description="Filter users joined on/after this date"),
#     date_to: Optional[datetime] = Query(None, description="Filter users joined on/before this date"),
#     sort_by: Optional[str] = Query("date_joined", description="Field to sort by: name, date_joined, email, status"),
#     sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
#     include_deleted: bool = Query(False, description="Include deleted users in export"),
#     fields: Optional[str] = Query(None, description="Comma-separated list of fields to include in export"),
#     admin_request: Request = None,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Export filtered user list to CSV.
#     Admin-only access with comprehensive filtering options.
#     """
#     try:
#         # Validate sort_by parameter
#         valid_sort_fields = ["name", "date_joined", "email", "status"]
#         if sort_by not in valid_sort_fields:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid sort_by. Must be one of: {valid_sort_fields}")
        
#         # Validate sort_order parameter
#         valid_sort_orders = ["asc", "desc"]
#         if sort_order not in valid_sort_orders:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid sort_order. Must be one of: {valid_sort_orders}")
        
#         # Validate status parameter
#         valid_statuses = ["active", "inactive", "banned", "deleted"]
#         if status and status not in valid_statuses:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid status. Must be one of: {valid_statuses}")
        
#         # Validate date range
#         if date_from and date_to and date_to < date_from:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "date_to must be after date_from")
        
#         # Parse fields parameter
#         export_fields = None
#         if fields:
#             export_fields = [field.strip() for field in fields.split(",") if field.strip()]
        
#         # Convert string values to enums
#         status_enum = None
#         if status:
#             if status == "active":
#                 status_enum = UserStatus.ACTIVE
#             elif status == "inactive":
#                 status_enum = UserStatus.INACTIVE
#             elif status == "banned":
#                 status_enum = UserStatus.BANNED
        
#         sort_field_enum = None
#         if sort_by == "name":
#             sort_field_enum = SortField.NAME
#         elif sort_by == "date_joined":
#             sort_field_enum = SortField.DATE_JOINED
#         elif sort_by == "email":
#             sort_field_enum = SortField.EMAIL
#         elif sort_by == "status":
#             sort_field_enum = SortField.STATUS
        
#         sort_order_enum = SortOrder.ASC if sort_order == "asc" else SortOrder.DESC
        
#         # Get client IP for logging
#         ip_address = get_client_ip(admin_request)
        
#         # Create export request model
#         export_request = UserExportRequest(
#             name=name,
#             email=email,
#             status=status_enum,
#             date_from=date_from,
#             date_to=date_to,
#             sort_by=sort_field_enum,
#             sort_order=sort_order_enum,
#             include_deleted=include_deleted,
#             fields=export_fields
#         )
        
#         # Perform export through service
#         result = await admin_users_service.export_users_to_csv(export_request, token, ip_address)
        
#         return result
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"Error in export_users: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error performing export: {str(e)}"        )

@router.get("/users/export-csv", dependencies=[Depends(security_scheme)])
async def export_users_csv(
    search: Optional[str] = Query(None, description="Search in name, email, or phone"),
    status: Optional[str] = Query(None, description="Filter by status: active, inactive, banned, deleted"),
    role: Optional[str] = Query(None, description="Filter by role: Captain, Member, or Moderator"),
    # date_from: Optional[datetime] = Query(None, description="Filter users joined on/after this date"),
    # date_to: Optional[datetime] = Query(None, description="Filter users joined on/before this date"),
    sort_by: Optional[str] = Query("date_joined", description="Sort by field: name or date_joined"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Current page number"),
    limit: int = Query(10, ge=1, le=100, description="Number of users per page"),
    current_admin: dict = Depends(get_current_admin)
):
    """
    Export filtered users as CSV file with the same filters and pagination as get_users.
    Admin-only access. Returns CSV blob for frontend developers.
    """
    try:
        # Validate sort_by parameter
        valid_sort_fields = ["name", "date_joined"]
        if sort_by not in valid_sort_fields:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid sort_by. Must be one of: {valid_sort_fields}",
                data=None
            )
        
        # Validate sort_order parameter
        valid_sort_orders = ["asc", "desc"]
        if sort_order not in valid_sort_orders:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid sort_order. Must be one of: {valid_sort_orders}",
                data=None
            )
        
        # Validate status parameter
        valid_statuses = ["active", "inactive", "banned", "deleted"]
        if status and status not in valid_statuses:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid status. Must be one of: {valid_statuses}",
                data=None
            )
        
        # Validate role parameter
        valid_roles = ["Captain", "Member", "Moderator"]
        if role and role not in valid_roles:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid role. Must be one of: {valid_roles}",
                data=None
            )
        
        # Convert string values to enums
        status_enum = None
        if status:
            if status == "active":
                status_enum = UserStatus.ACTIVE
            elif status == "inactive":
                status_enum = UserStatus.INACTIVE
            elif status == "banned":
                status_enum = UserStatus.BANNED
            elif status == "deleted":
                status_enum = UserStatus.DELETED
        
        role_enum = None
        if role:
            if role == "Captain":
                role_enum = UserRole.CAPTAIN
            elif role == "Member":
                role_enum = UserRole.MEMBER
            elif role == "Moderator":
                role_enum = UserRole.MODERATOR
        
        sort_field_enum = SortField.NAME if sort_by == "name" else SortField.DATE_JOINED
        sort_order_enum = SortOrder.ASC if sort_order == "asc" else SortOrder.DESC
        
        # For CSV export, respect pagination parameters with max limit of 100
        # Create request model with the provided page and limit
        request = UserListRequest(
            search=search,
            status=status_enum,
            role=role_enum,
            sort_by=sort_field_enum,
            sort_order=sort_order_enum,
            page=page,  # Use the page parameter from the request
            limit=min(limit, 100)  # Respect the limit parameter but cap at 100
        )
        
        # Test database connection first
        try:
            from .db import users_collection
            # Try to count documents to test connection
            user_count = await users_collection.count_documents({})
            print(f"CSV Export - Database connection test: Found {user_count} total users")
        except Exception as db_error:
            print(f"CSV Export - Database connection failed: {db_error}")
            return create_response(
                status_code=500,
                status="error",
                message=f"Database connection failed: {str(db_error)}",
                data=None
            )
        
        # Get users from service
        try:
            result = await admin_users_service.get_users(request)
            print(f"CSV Export - Service call successful")
        except Exception as service_error:
            print(f"CSV Export - Service call failed with exception: {service_error}")
            return create_response(
                status_code=500,
                status="error",
                message=f"Service call failed: {str(service_error)}",
                data=None
            )
        
        # Debug logging
        print(f"CSV Export - Result type: {type(result)}")
        print(f"CSV Export - Result: {result}")
        
        # Convert Pydantic model to dictionary for CSV generation
        if hasattr(result, 'model_dump'):
            # For Pydantic v2
            result_data = result.model_dump()
        elif hasattr(result, 'dict'):
            # For Pydantic v1
            result_data = result.dict()
        else:
            # Fallback for other types
            result_data = result
        
        print(f"CSV Export - Result data: {result_data}")
        print(f"CSV Export - Has users key: {'users' in result_data if result_data else 'None'}")
        if result_data and 'users' in result_data:
            print(f"CSV Export - Users count: {len(result_data['users'])}")
        
        # Check if we have valid result data
        if not result_data:
            print("CSV Export - No result data received from service")
            return create_response(
                status_code=400,
                status="error",
                message="No data received from user service",
                data=None
            )
        
        # Check if the service call was successful
        if not result_data.get('success', False):
            print(f"CSV Export - Service call failed: {result_data.get('message', 'Unknown error')}")
            return create_response(
                status_code=400,
                status="error",
                message=f"Service error: {result_data.get('message', 'Unknown error')}",
                data=None
            )
        
        # Generate CSV content
        import csv
        import io
        
        # Create CSV buffer
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        
        # Write CSV header
        if result_data and 'users' in result_data and result_data['users']:
            print(f"CSV Export - Found {len(result_data['users'])} users to export")
            
            # Define custom headers and field mappings (excluding user_id)
            custom_headers = ["Full Name", "Email", "Phone", "Role", "Status", "Date of Joining"]
            field_mappings = ["full_name", "email", "phone", "role", "status", "date_joined"]
            
            # Write custom headers
            csv_writer.writerow(custom_headers)
            
            # Write user data
            for user in result_data['users']:
                # Convert all values to strings and handle None values
                row = []
                for field in field_mappings:
                    value = user.get(field, '')
                    if value is None:
                        row.append('')
                    elif field == 'date_joined' and hasattr(value, 'date'):  # For date_joined, show only date
                        row.append(value.date().strftime('%Y-%m-%d'))
                    elif hasattr(value, 'isoformat'):  # Other datetime objects
                        row.append(value.isoformat())
                    else:
                        row.append(str(value))
                csv_writer.writerow(row)
        else:
            # No users found - create empty CSV with headers
            print("CSV Export - No users found, creating empty CSV")
            print(f"CSV Export - Result data keys: {list(result_data.keys()) if result_data else 'None'}")
            if result_data and 'users' in result_data:
                print(f"CSV Export - Users array: {result_data['users']}")
            
            # Define default headers for user data (excluding user_id)
            default_headers = ["Full Name", "Email", "Phone", "Role", "Status", "Date of Joining"]
            csv_writer.writerow(default_headers)
            # Write a message row indicating no data
            csv_writer.writerow(['No users found matching the specified criteria'])
        
        # Get CSV content as string
        csv_content = csv_buffer.getvalue()
        csv_buffer.close()
        
        # Create CSV blob response
        from fastapi.responses import Response
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"users_export_{timestamp}.csv"
        
        # Return CSV response
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8"
            }
        )
        
    except Exception as e:
        print(f"Error in export_users_csv: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error exporting users to CSV: {str(e)}",
            data=None
        )

async def get_current_admin_or_captain(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    """Get current admin or captain from JWT token"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email = payload.get("sub")
        user_id = payload.get("user_id")
        role = payload.get("role")
        
        if email is None:
            raise HTTPException(HTTP_401_UNAUTHORIZED, "Invalid token")
        
        # Check if it's an admin session
        session = await sessions_collection.find_one({"token": token, "email": email})
        if session:
            # It's an admin session
            return {"user_id": email, "email": email, "role": "admin", "type": "admin"}
        
        # Check if it's a captain session (from club service)
        if user_id and role == "Captain":
            # Verify the user exists and is a captain
            from services.club.db import get_user_collection
            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            if user and user.get("role") == "Captain":
                return {
                    "user_id": user_id,
                    "email": user.get("email", ""),
                    "role": "Captain",
                    "type": "captain"
                }
        
        raise HTTPException(HTTP_401_UNAUTHORIZED, "Invalid token or insufficient permissions")
        
    except Exception as e:
        raise HTTPException(HTTP_401_UNAUTHORIZED, f"Authentication failed: {str(e)}")

@router.get("/users/{user_id}")
async def get_user_by_id(
    user_id: str,
    current_user: dict = Depends(get_current_admin_or_captain)
):
    """
    Get a specific user by ID.
    Admin or Captain access.
    """
    try:
        user = await admin_users_service.get_user_by_id(user_id)
        if not user:
            return create_response(
                status_code=404,
                status="error",
                message="User not found",
                data=None
            )
        
        # Get member and moderator counts from clubs table
        club_counts = await admin_users_service.get_user_club_counts(user_id)
        
        # Convert Pydantic model to dictionary and handle datetime serialization
        def convert_to_serializable(obj):
            """Convert Pydantic models to dictionaries and handle datetime serialization"""
            if hasattr(obj, 'model_dump'):
                # For Pydantic v2
                return convert_datetime_to_iso(obj.model_dump())
            elif hasattr(obj, 'dict'):
                # For Pydantic v1
                return convert_datetime_to_iso(obj.dict())
            elif isinstance(obj, dict):
                return convert_datetime_to_iso(obj)
            elif isinstance(obj, list):
                return [convert_to_serializable(item) for item in obj]
            else:
                return convert_datetime_to_iso(obj)
        
        def convert_datetime_to_iso(obj):
            """Recursively convert datetime objects to ISO format strings"""
            if isinstance(obj, dict):
                return {key: convert_datetime_to_iso(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [convert_datetime_to_iso(item) for item in obj]
            elif hasattr(obj, 'isoformat'):  # datetime objects
                return obj.isoformat()
            else:
                return obj
        
        # Convert user data to be JSON serializable
        serializable_user = convert_to_serializable(user)
        
        # Add club counts to the response
        serializable_user['club_counts'] = club_counts
        
        return create_response(
            status_code=200,
            status="success",
            message="User retrieved successfully",
            data={
                "user": serializable_user
            }
        )
        
    except Exception as e:
        print(f"Error in get_user_by_id: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error retrieving user: {str(e)}",
            data=None
        )

@router.get("/users", dependencies=[Depends(security_scheme)])
async def get_users(
    search: Optional[str] = Query(None, description="Search in name, email, or phone"),
    status: Optional[str] = Query(None, description="Filter by status: active, inactive, banned, deleted"),
    role: Optional[str] = Query(None, description="Filter by role: Captain, Member, or Moderator"),
    # date_from: Optional[datetime] = Query(None, description="Filter users joined on/after this date"),
    # date_to: Optional[datetime] = Query(None, description="Filter users joined on/before this date"),
    sort_by: Optional[str] = Query("date_joined", description="Sort by field: name or date_joined"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Current page number"),
    limit: int = Query(10, ge=1, le=100, description="Number of users per page"),
    current_admin: dict = Depends(get_current_admin)
):
    """
    Get paginated list of registered users with search, filtering, and sorting.
    Admin-only access.
    """
    try:
        # Validate sort_by parameter
        valid_sort_fields = ["name", "date_joined"]
        if sort_by not in valid_sort_fields:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid sort_by. Must be one of: {valid_sort_fields}",
                data=None
            )
        
        # Validate sort_order parameter
        valid_sort_orders = ["asc", "desc"]
        if sort_order not in valid_sort_orders:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid sort_order. Must be one of: {valid_sort_orders}",
                data=None
            )
        
        # Validate status parameter
        valid_statuses = ["active", "inactive", "banned", "deleted"]
        if status and status not in valid_statuses:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid status. Must be one of: {valid_statuses}",
                data=None
            )
        
        # Validate role parameter
        valid_roles = ["Captain", "Member", "Moderator"]
        if role and role not in valid_roles:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid role. Must be one of: {valid_roles}",
                data=None
            )
        
        # Convert string values to enums
        status_enum = None
        if status:
            if status == "active":
                status_enum = UserStatus.ACTIVE
            elif status == "inactive":
                status_enum = UserStatus.INACTIVE
            elif status == "banned":
                status_enum = UserStatus.BANNED
            elif status == "deleted":
                status_enum = UserStatus.DELETED
        
        role_enum = None
        if role:
            if role == "Captain":
                role_enum = UserRole.CAPTAIN
            elif role == "Member":
                role_enum = UserRole.MEMBER
            elif role == "Moderator":
                role_enum = UserRole.MODERATOR
        
        sort_field_enum = SortField.NAME if sort_by == "name" else SortField.DATE_JOINED
        sort_order_enum = SortOrder.ASC if sort_order == "asc" else SortOrder.DESC
        
        # Create request model
        request = UserListRequest(
            search=search,
            status=status_enum,
            role=role_enum,
            sort_by=sort_field_enum,
            sort_order=sort_order_enum,
            page=page,
            limit=limit
        )
        
        # Get users from service
        result = await admin_users_service.get_users(request)
        
        # Convert Pydantic model to dictionary for JSON serialization
        if hasattr(result, 'model_dump'):
            # For Pydantic v2
            result_data = result.model_dump()
        elif hasattr(result, 'dict'):
            # For Pydantic v1
            result_data = result.dict()
        else:
            # Fallback for other types
            result_data = result
        
        # Convert datetime objects to ISO format strings for JSON serialization
        def convert_datetime_to_iso(obj):
            """Recursively convert datetime objects to ISO format strings"""
            if isinstance(obj, dict):
                return {key: convert_datetime_to_iso(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [convert_datetime_to_iso(item) for item in obj]
            elif hasattr(obj, 'isoformat'):  # datetime objects
                return obj.isoformat()
            else:
                return obj
        
        # Convert all datetime objects in the result
        serializable_data = convert_datetime_to_iso(result_data)
        
        # Return success response using create_response
        return create_response(
            status_code=200,
            status="success",
            message="Users retrieved successfully",
            data=serializable_data
        )
        
    except Exception as e:
        print(f"Error in get_users: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error retrieving users: {str(e)}",
            data=None
        )


async def export_users_csv(
    search: Optional[str] = Query(None, description="Search in name, email, or phone"),
    status: Optional[str] = Query(None, description="Filter by status: active, inactive, banned, deleted"),
    role: Optional[str] = Query(None, description="Filter by role: Captain, Member, or Moderator"),
    # date_from: Optional[datetime] = Query(None, description="Filter users joined on/after this date"),
    # date_to: Optional[datetime] = Query(None, description="Filter users joined on/before this date"),
    sort_by: Optional[str] = Query("date_joined", description="Sort by field: name or date_joined"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Current page number"),
    limit: int = Query(10, ge=1, le=100, description="Number of users per page"),
    current_admin: dict = Depends(get_current_admin)
):
    """
    Export filtered users as CSV file with the same filters and pagination as get_users.
    Admin-only access. Returns CSV blob for frontend developers.
    """
    try:
        # Validate sort_by parameter
        valid_sort_fields = ["name", "date_joined"]
        if sort_by not in valid_sort_fields:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid sort_by. Must be one of: {valid_sort_fields}",
                data=None
            )
        
        # Validate sort_order parameter
        valid_sort_orders = ["asc", "desc"]
        if sort_order not in valid_sort_orders:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid sort_order. Must be one of: {valid_sort_orders}",
                data=None
            )
        
        # Validate status parameter
        valid_statuses = ["active", "inactive", "banned", "deleted"]
        if status and status not in valid_statuses:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid status. Must be one of: {valid_statuses}",
                data=None
            )
        
        # Validate role parameter
        valid_roles = ["Captain", "Member", "Moderator"]
        if role and role not in valid_roles:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid role. Must be one of: {valid_roles}",
                data=None
            )
        
        # Convert string values to enums
        status_enum = None
        if status:
            if status == "active":
                status_enum = UserStatus.ACTIVE
            elif status == "inactive":
                status_enum = UserStatus.INACTIVE
            elif status == "banned":
                status_enum = UserStatus.BANNED
            elif status == "deleted":
                status_enum = UserStatus.DELETED
        
        role_enum = None
        if role:
            if role == "Captain":
                role_enum = UserRole.CAPTAIN
            elif role == "Member":
                role_enum = UserRole.MEMBER
            elif role == "Moderator":
                role_enum = UserRole.MODERATOR
        
        sort_field_enum = SortField.NAME if sort_by == "name" else SortField.DATE_JOINED
        sort_order_enum = SortOrder.ASC if sort_order == "asc" else SortOrder.DESC
        
        # For CSV export, we want all users without pagination
        # Create request model with high limit to get all users
        request = UserListRequest(
            search=search,
            status=status_enum,
            role=role_enum,
            sort_by=sort_field_enum,
            sort_order=sort_order_enum,
            page=1,  # Always start from first page
            limit=10000  # High limit to get all users
        )

        
        # Test database connection first
        try:
            from .db import users_collection
            # Try to count documents to test connection
            user_count = await users_collection.count_documents({})
            print(f"CSV Export - Database connection test: Found {user_count} total users")
        except Exception as db_error:
            print(f"CSV Export - Database connection failed: {db_error}")
            return create_response(
                status_code=500,
                status="error",
                message=f"Database connection failed: {str(db_error)}",
                data=None
            )
        
        # Get users from service
        try:
            result = await admin_users_service.get_users(request)
            print(f"CSV Export - Service call successful")
        except Exception as service_error:
            print(f"CSV Export - Service call failed with exception: {service_error}")
            return create_response(
                status_code=500,
                status="error",
                message=f"Service call failed: {str(service_error)}",
                data=None
            )
        
        # Debug logging
        print(f"CSV Export - Result type: {type(result)}")
        print(f"CSV Export - Result: {result}")
        
        # Convert Pydantic model to dictionary for CSV generation
        if hasattr(result, 'model_dump'):
            # For Pydantic v2
            result_data = result.model_dump()
        elif hasattr(result, 'dict'):
            # For Pydantic v1
            result_data = result.dict()
        else:
            # Fallback for other types
            result_data = result
        
        print(f"CSV Export - Result data: {result_data}")
        print(f"CSV Export - Has users key: {'users' in result_data if result_data else False}")
        if result_data and 'users' in result_data:
            print(f"CSV Export - Users count: {len(result_data['users'])}")
        
        # Check if we have valid result data
        if not result_data:
            print("CSV Export - No result data received from service")
            return create_response(
                status_code=400,
                status="error",
                message="No data received from user service",
                data=None
            )
        
        # Check if the service call was successful
        if not result_data.get('success', False):
            print(f"CSV Export - Service call failed: {result_data.get('message', 'Unknown error')}")
            return create_response(
                status_code=400,
                status="error",
                message=f"Service error: {result_data.get('message', 'Unknown error')}",
                data=None
            )
        
        # Generate CSV content
        import csv
        import io
        
        # Create CSV buffer
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        
        # Write CSV header
        if result_data and 'users' in result_data and result_data['users']:
            print(f"CSV Export - Found {len(result_data['users'])} users to export")
            
            # Define custom headers and field mappings (excluding user_id)
            custom_headers = ["Full Name", "Email", "Phone", "Role", "Status", "Date of Joining"]
            field_mappings = ["full_name", "email", "phone", "role", "status", "date_joined"]
            
            # Write custom headers
            csv_writer.writerow(custom_headers)
            
            # Write user data
            for user in result_data['users']:
                # Convert all values to strings and handle None values
                row = []
                for field in field_mappings:
                    value = user.get(field, '')
                    if value is None:
                        row.append('')
                    elif field == 'date_joined' and hasattr(value, 'date'):  # For date_joined, show only date
                        row.append(value.date().strftime('%Y-%m-%d'))
                    elif hasattr(value, 'isoformat'):  # Other datetime objects
                        row.append(value.isoformat())
                    else:
                        row.append(str(value))
                csv_writer.writerow(row)
        else:
            # No users found - create empty CSV with headers
            print("CSV Export - No users found, creating empty CSV")
            print(f"CSV Export - Result data keys: {list(result_data.keys()) if result_data else 'None'}")
            if result_data and 'users' in result_data:
                print(f"CSV Export - Users array: {result_data['users']}")
            
            # Define default headers for user data (excluding user_id)
            default_headers = ["Full Name", "Email", "Phone", "Role", "Status", "Date of Joining"]
            csv_writer.writerow(default_headers)
            # Write a message row indicating no data
            csv_writer.writerow(['No users found matching the specified criteria'])
        
        # Get CSV content as string
        csv_content = csv_buffer.getvalue()
        csv_buffer.close()
        
        # Create CSV blob response
        from fastapi.responses import Response
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"users_export_{timestamp}.csv"
        
        # Return CSV response
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8"
            }
        )
        
    except Exception as e:
        print(f"Error in export_users_csv: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error exporting users to CSV: {str(e)}",
            data=None
        )

@router.get("/users/debug", dependencies=[Depends(security_scheme)])
async def debug_users_service(
    current_admin: dict = Depends(get_current_admin)
):
    """
    Debug endpoint to test the users service directly
    """
    try:
        # Test database connection
        from .db import users_collection
        user_count = await users_collection.count_documents({})
        
        # Test service call with minimal request
        from .models import UserListRequest, SortField, SortOrder
        test_request = UserListRequest(
            search=None,
            status=None,
            role=None,
            sort_by=SortField.DATE_JOINED,
            sort_order=SortOrder.DESC,
            page=1,
            limit=5
        )
        
        result = await admin_users_service.get_users(test_request)
        
        return create_response(
            status_code=200,
            status="success",
            message="Debug test completed",
            data={
                "database_user_count": user_count,
                "service_result_type": str(type(result)),
                "service_result": result,
                "service_success": result.get('success', False) if isinstance(result, dict) else 'Not a dict'
            }
        )
        
    except Exception as e:
        print(f"Error in debug_users_service: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Debug test failed: {str(e)}",
            data=None
        )

@router.put("/users/{user_id}")
async def edit_user(
    user_id: str,
    request: EditUserRequest,
    admin_request: Request,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Edit an existing user.
    Admin-only access.
    """
    try:
        # Get client IP for audit logging
        ip_address = get_client_ip(admin_request)
        
        # Extract email from current_admin
        admin_email = current_admin.get("email")
        
        # Edit user through service
        result = await admin_users_service.edit_user(user_id, request, admin_email, ip_address)
        
        if result["success"]:
            # Convert any datetime objects to ISO format for JSON serialization
            def convert_datetime_to_iso(obj):
                """Recursively convert datetime objects to ISO format strings"""
                if isinstance(obj, dict):
                    return {key: convert_datetime_to_iso(value) for key, value in obj.items()}
                elif isinstance(obj, list):
                    return [convert_datetime_to_iso(item) for item in obj]
                elif hasattr(obj, 'isoformat'):  # datetime objects
                    return obj.isoformat()
                else:
                    return obj
            
            # Convert Pydantic models to dictionaries and handle datetime serialization
            def convert_to_serializable(obj):
                """Convert Pydantic models to dictionaries and handle datetime serialization"""
                if hasattr(obj, 'model_dump'):
                    # For Pydantic v2
                    return convert_datetime_to_iso(obj.model_dump())
                elif hasattr(obj, 'dict'):
                    # For Pydantic v1
                    return convert_datetime_to_iso(obj.dict())
                elif isinstance(obj, dict):
                    return convert_datetime_to_iso(obj)
                elif isinstance(obj, list):
                    return [convert_to_serializable(item) for item in obj]
                else:
                    return convert_datetime_to_iso(obj)
            
            # Convert all data to be JSON serializable
            serializable_user = convert_to_serializable(result["user"])
            serializable_changes = convert_to_serializable(result["changes"])
            
            return create_response(
                status_code=200,
                status="success",
                message=result["message"],
                data={
                    "user_id": result["user_id"],
                    "user": serializable_user,
                    # "changes": serializable_changes
                }
            )
        else:
            # Handle different error types with appropriate status codes
            if result["error"] == "USER_NOT_FOUND":
                return create_response(
                    status_code=404,
                    status="error",
                    message=result["message"],
                    data=None
                )
            elif result["error"] == "EMAIL_EXISTS":
                return create_response(
                    status_code=409,
                    status="error",
                    message=result["message"],
                    data=None
                )
            elif result["error"] == "USER_DELETED":
                return create_response(
                    status_code=400,
                    status="error",
                    message=result["message"],
                    data=None
                )
            else:
                return create_response(
                    status_code=400,
                    status="error",
                    message=result["message"],
                    data=None
                )
        
    except Exception as e:
        print(f"Error in edit_user: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error updating user: {str(e)}",
            data=None
        )

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin_request: Request,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Soft delete a user.
    Admin-only access.
    """
    try:
        # Get client IP for audit logging
        ip_address = get_client_ip(admin_request)
        
        # Extract admin email from the token
        admin_email = current_admin.get("email")
        
        # Delete user through service
        result = await admin_users_service.delete_user(user_id, admin_email, ip_address)
        
        if result["success"]:
            return create_response(
                status_code=200,
                status="success",
                message=result["message"],
                data={
                    "user_id": result["user_id"],
                    "deleted_at": result.get("deleted_at"),
                    "email_sent": result.get("email_sent", False),
                    "details": {
                        "status_updated": "inactive",
                        "membership_status_updated": "inactive",
                        "is_deleted": True,
                        "deleted_at": result.get("deleted_at")
                    }
                }
            )
        else:
            if result["error"] == "USER_NOT_FOUND":
                return create_response(
                    status_code=404,
                    status="error",
                    message=result["message"],
                    data=None
                )
            elif result["error"] == "ALREADY_DELETED":
                return create_response(
                    status_code=400,
                    status="error",
                    message=result["message"],
                    data=None
                )
            else:
                return create_response(
                    status_code=400,
                    status="error",
                    message=result["message"],
                    data=None
                )
        
    except Exception as e:
        print(f"Error in delete_user: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error deleting user: {str(e)}",
            data=None
        )

@router.post("/users/temporary-delete")
async def temporary_delete_user(
    request: AdminDeletionRequest,
    admin_request: Request,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Temporarily delete a user (captain/member/moderator) and pause all associated clubs/memberships.
    Admin-only access.
    """
    try:
        # Get client IP for audit logging
        ip_address = get_client_ip(admin_request)
        
        # Extract admin email from the token
        admin_email = current_admin.get("email")
        
        # Use the comprehensive admin deletion service
        result = await admin_deletion_service.temporarily_delete_user(request, admin_email, ip_address)
        
        if result.success:
            return create_response(
                status_code=200,
                status="success",
                message=result.message,
                data=result.data
            )
        else:
            return create_response(
                status_code=400,
                status="error",
                message=result.message,
                data=result.data
            )
            
    except Exception as e:
        return create_response(
            status_code=500,
            status="error",
            message=f"Error temporarily deleting user: {str(e)}",
            data=None
        )

@router.post("/users/permanent-delete")
async def permanent_delete_user(
    request: AdminDeletionRequest,
    admin_request: Request,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Permanently delete a user (captain/member/moderator) and all associated clubs/memberships.
    Admin-only access.
    """
    try:
        # Get client IP for audit logging
        ip_address = get_client_ip(admin_request)
        
        # Extract admin email from the token
        admin_email = current_admin.get("email")
        
        # Use the comprehensive admin deletion service
        result = await admin_deletion_service.permanently_delete_user(request, admin_email, ip_address)
        
        if result.success:
            return create_response(
                status_code=200,
                status="success",
                message=result.message,
                data=result.data
            )
        else:
            return create_response(
                status_code=400,
                status="error",
                message=result.message,
                data=result.data
            )
            
    except Exception as e:
        return create_response(
            status_code=500,
            status="error",
            message=f"Error permanently deleting user: {str(e)}",
            data=None
        )

@router.post("/users/reactivate")
async def reactivate_user(
    request: AdminReactivationRequest,
    admin_request: Request,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Reactivate a temporarily deleted user and resume all associated clubs/memberships.
    Admin-only access.
    """
    try:
        # Get client IP for audit logging
        ip_address = get_client_ip(admin_request)
        
        # Extract admin email from the token
        admin_email = current_admin.get("email")
        
        # Use the comprehensive admin deletion service
        result = await admin_deletion_service.reactivate_user(request, admin_email, ip_address)
        
        if result.success:
            return create_response(
                status_code=200,
                status="success",
                message=result.message,
                data=result.data
            )
        else:
            return create_response(
                status_code=400,
                status="error",
                message=result.message,
                data=result.data
            )
            
    except Exception as e:
        return create_response(
            status_code=500,
            status="error",
            message=f"Error reactivating user: {str(e)}",
            data=None
        )

class UpdateUserStatusRequest(BaseModel):
    status: str

# @router.put("/users/{user_id}/status")
# async def update_user_status(
#     user_id: str,
#     request: UpdateUserStatusRequest,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Update user status (active/inactive/banned).
#     Admin-only access.
#     """
#     try:
#         # Validate status
#         valid_statuses = ["active", "inactive", "banned", "deleted"]
#         if request.status not in valid_statuses:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid status. Must be one of: {valid_statuses}")
        
#         # Update user status
#         success = await admin_users_service.update_user_status(user_id, request.status)
        
#         if not success:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "User not found or status update failed")
        
#         return {
#             "success": True,
#             "message": f"User status updated to {request.status}",
#             "user_id": user_id,
#             "status": request.status
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         print(f"Error in update_user_status: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error updating user status: {str(e)}")

# @router.get("/users/statistics")
# async def get_user_statistics(
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get user statistics for the admin dashboard.
#     Admin-only access.
#     """
#     try:
#         statistics = await admin_users_service.get_user_statistics()
        
#         return {
#             "success": True,
#             "message": "User statistics retrieved successfully",
#             "statistics": statistics
#         }
        
#     except Exception as e:
#         print(f"Error in get_user_statistics: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving user statistics: {str(e)}")

# @router.get("/users/{user_id}/audit-logs")
# async def get_user_audit_logs(
#     user_id: str,
#     limit: int = Query(50, ge=1, le=100, description="Number of audit logs to return"),
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get audit logs for a specific user.
#     Admin-only access.
#     """
#     try:
#         logs = await admin_users_service.get_audit_logs(user_id, limit)
        
#         return {
#             "success": True,
#             "message": "Audit logs retrieved successfully",
#             "user_id": user_id,
#             "logs": logs,
#             "count": len(logs)
#         }
        
#     except Exception as e:
#         print(f"Error in get_user_audit_logs: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving audit logs: {str(e)}")

# @router.get("/export-logs")
# async def get_export_logs(
#     admin_email: Optional[str] = Query(None, description="Filter by admin email"),
#     limit: int = Query(50, ge=1, le=100, description="Number of export logs to return"),
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get export logs for analytics and monitoring.
#     Admin-only access.
#     """
#     try:
#         logs = await admin_users_service.get_export_logs(admin_email, limit)
        
#         return {
#             "success": True,
#             "message": "Export logs retrieved successfully",
#             "logs": logs,
#             "count": len(logs)
#         }
        
#     except Exception as e:
#         print(f"Error in get_export_logs: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving export logs: {str(e)}")

# # Club Management Routes

@router.get("/clubs", dependencies=[Depends(security_scheme)])
async def get_clubs(
    search: Optional[str] = Query(None, description="Search by club name or owner name"),
    status: Optional[str] = Query(None, description="Filter by club status: approved, pending, rejected, inactive, deleted"),
    sort_by: Optional[str] = Query("created_date", description="Sort by field: name, owner, created_date, moderator_count, subscription_price, status"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    current_admin: dict = Depends(get_current_admin)
):
    """
    Get paginated list of registered clubs with search, filtering, and sorting.
    Admin-only access.
    
    Status filtering supports case-insensitive values: approved, pending, rejected, inactive, deleted
    """
    try:
        # Validate sort_by parameter
        valid_sort_fields = ["name", "owner", "created_date", "moderator_count", "subscription_price", "status"]
        if sort_by not in valid_sort_fields:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid sort_by. Must be one of: {valid_sort_fields}",
                data=None
            )
        
        # Validate sort_order parameter
        valid_sort_orders = ["asc", "desc"]
        if sort_order not in valid_sort_orders:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid sort_order. Must be one of: {valid_sort_orders}",
                data=None
            )
        
        # Validate status parameter (case-insensitive)
        valid_statuses = ["approved", "pending", "rejected", "inactive", "deleted"]
        if status and status.lower() not in [s.lower() for s in valid_statuses]:
            return create_response(
                status_code=400,
                status="error",
                message=f"Invalid status. Must be one of: {valid_statuses}",
                data=None
            )
        
        # Convert string values to enums (case-insensitive)
        status_enum = None
        if status:
            status_lower = status.lower()
            if status_lower == "approved":
                status_enum = ClubStatus.APPROVED
            elif status_lower == "pending":
                status_enum = ClubStatus.PENDING
            elif status_lower == "rejected":
                status_enum = ClubStatus.REJECTED
            elif status_lower == "inactive":
                status_enum = ClubStatus.INACTIVE
            elif status_lower == "deleted":
                status_enum = ClubStatus.DELETED
        
        sort_field_enum = None
        if sort_by == "name":
            sort_field_enum = ClubSortField.NAME
        elif sort_by == "owner":
            sort_field_enum = ClubSortField.OWNER
        elif sort_by == "created_date":
            sort_field_enum = ClubSortField.CREATED_DATE
        elif sort_by == "moderator_count":
            sort_field_enum = ClubSortField.MODERATOR_COUNT
        elif sort_by == "subscription_price":
            sort_field_enum = ClubSortField.SUBSCRIPTION_PRICE
        elif sort_by == "status":
            sort_field_enum = ClubSortField.STATUS
        
        sort_order_enum = SortOrder.ASC if sort_order == "asc" else SortOrder.DESC
        
        # Create request model
        request = ClubListRequest(
            search=search,
            status=status_enum,
            sort_by=sort_field_enum,
            sort_order=sort_order_enum,
            page=page,
            limit=limit
        )
        
        # Get clubs from service
        result = await admin_clubs_service.get_clubs(request)
        
        # Convert result to proper response format
        if hasattr(result, 'model_dump'):
            result_dict = result.model_dump()
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = result.dict()
        
        return create_response(
            status_code=200,
            status="success",
            message="Clubs retrieved successfully",
            data=result_dict
        )
        
    except Exception as e:
        print(f"Error in get_clubs: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error retrieving clubs: {str(e)}",
            data=None
        )

# @router.get("/clubs/search", response_model=ClubAdvancedSearchResponse)
# async def search_clubs_advanced(
#     # Filter parameters
#     club_name: Optional[str] = Query(None, description="Partial or full club name"),
#     owner_name: Optional[str] = Query(None, description="Partial or full owner name"), 
#     email: Optional[str] = Query(None, description="Partial or full email"),
#     phone: Optional[str] = Query(None, description="Exact phone number match"),
#     status: Optional[str] = Query(None, description="Filter by status: approved, pending, suspended"),
    
#     # Date range filters
#     date_from: Optional[str] = Query(None, description="Filter clubs created on/after this date (YYYY-MM-DD)"),
#     date_to: Optional[str] = Query(None, description="Filter clubs created on/before this date (YYYY-MM-DD)"),
    
#     # Sorting parameters
#     sort_by: Optional[str] = Query("date_created", description="Sort by field: club_name, owner_name, date_created, subscription_price, moderator_count, status"),
#     sort_order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    
#     # Pagination parameters
#     page: int = Query(1, ge=1, description="Page number (default: 1)"),
#     limit: int = Query(10, ge=1, le=100, description="Number of results per page (default: 10)"),
    
#     request: Request = None,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Advanced search for clubs and club owners with comprehensive filtering and sorting.
    
#     Supports:
#     - Partial matching for club_name, owner_name, and email
#     - Exact matching for phone and status
#     - Date range filtering for creation dates
#     - Comprehensive sorting by all major fields
#     - Pagination with configurable page size
#     - Performance optimized with proper indexing
#     - Search result logging and analytics
    
#     Admin-only access.
#     """
#     try:
#         # Get admin email from token
#         # Token is already validated by get_current_admin dependency and contains the email
#         admin_email = token
        
#         # Get client IP address
#         ip_address = None
#         if request:
#             forwarded_for = request.headers.get("x-forwarded-for")
#             if forwarded_for:
#                 ip_address = forwarded_for.split(",")[0].strip()
#             else:
#                 ip_address = getattr(request.client, "host", None)
        
#         # Validate status parameter
#         if status:
#             valid_statuses = ["approved", "pending", "suspended"]
#             if status not in valid_statuses:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid status. Must be one of: {valid_statuses}")
        
#         # Validate sort_by parameter
#         if sort_by:
#             valid_sort_fields = ["club_name", "owner_name", "date_created", "subscription_price", "moderator_count", "status"]
#             if sort_by not in valid_sort_fields:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid sort_by. Must be one of: {valid_sort_fields}")
        
#         # Validate sort_order parameter
#         if sort_order:
#             valid_sort_orders = ["asc", "desc"]
#             if sort_order not in valid_sort_orders:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid sort_order. Must be one of: {valid_sort_orders}")
        
#         # Parse and validate date parameters
#         parsed_date_from = None
#         parsed_date_to = None
        
#         if date_from:
#             try:
#                 parsed_date_from = datetime.strptime(date_from, "%Y-%m-%d")
#             except ValueError:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid date_from format. Use YYYY-MM-DD")
        
#         if date_to:
#             try:
#                 parsed_date_to = datetime.strptime(date_to, "%Y-%m-%d")
#             except ValueError:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid date_to format. Use YYYY-MM-DD")
        
#         # Validate date range
#         if parsed_date_from and parsed_date_to and parsed_date_to < parsed_date_from:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "date_to must be after date_from")
        
#         # Create search request
#         search_request = ClubAdvancedSearchRequest(
#             club_name=club_name,
#             owner_name=owner_name,
#             email=email,
#             phone=phone,
#             status=ClubStatus(status) if status else None,
#             date_from=parsed_date_from,
#             date_to=parsed_date_to,
#             sort_by=ClubSearchSortField(sort_by) if sort_by else ClubSearchSortField.DATE_CREATED,
#             sort_order=SortOrder(sort_order) if sort_order else SortOrder.DESC,
#             page=page,
#             limit=limit
#         )
        
#         # Execute search
#         result = await admin_clubs_service.search_clubs_advanced(search_request, admin_email, ip_address)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in search_clubs_advanced: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Validation error: {str(ve)}")
#     except Exception as e:
#         print(f"Error in search_clubs_advanced: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error searching clubs: {str(e)}")

# @router.get("/clubs/statistics")
# async def get_club_statistics(
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get club statistics for the admin dashboard.
#     Admin-only access.
#     """
#     try:
#         statistics = await admin_clubs_service.get_club_statistics()
        
#         return {
#             "success": True,
#             "message": "Club statistics retrieved successfully",
#             "statistics": statistics
#         }
        
#     except Exception as e:
#         print(f"Error in get_club_statistics: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving club statistics: {str(e)}")

@router.get("/clubs/{club_id}", dependencies=[Depends(security_scheme)])
async def get_club_details(
    club_id: str,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Get comprehensive club details including owner, moderators, financials, and activity.
    Admin-only access.
    """
    try:
        result = await admin_clubs_service.get_club_details(club_id)
        
        # Convert result to proper response format
        if hasattr(result, 'model_dump'):
            result_dict = result.model_dump()
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = result.dict()
        
        return create_response(
            status_code=200,
            status="success",
            message="Club details retrieved successfully",
            data=result_dict
        )
        
    except ValueError as e:
        return create_response(
            status_code=404,
            status="error",
            message=str(e),
            data=None
        )
    except Exception as e:
        print(f"Error in get_club_details: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error retrieving club details: {str(e)}",
            data=None
        )

@router.put("/clubs/{club_id}", dependencies=[Depends(security_scheme)])
async def update_club_details(
    club_id: str,
    request: ClubUpdateDetailsRequest,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Update club details including logo URL, name, descriptions, status, and owner name.
    Admin-only access.
    """
    try:
        result = await admin_clubs_service.update_club_details(
            club_id=club_id,
            request=request,
            admin_email=current_admin.get("email", "")
        )
        return create_response(
            status_code=200,
            status="success",
            message="Club details updated successfully",
            data=result
        )
        
    except ValueError as e:
        return create_response(
            status_code=404,
            status="error",
            message=str(e),
            data=None
        )
    except Exception as e:
        print(f"Error in update_club_details: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error updating club details: {str(e)}",
            data=None
        )

# @router.patch("/clubs/{club_id}/status")
# async def update_club_status(
#     club_id: str,
#     request: ClubStatusUpdateRequest,
#     admin_request: Request,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Update club status (ban, suspend, reactivate).
#     Admin-only access.
#     """
#     try:
#         # Get client IP
#         client_ip = get_client_ip(admin_request)
        
#         result = await admin_clubs_service.update_club_status(club_id, request, token, client_ip)
#         return result
        
#     except ValueError as e:
#         raise HTTPException(HTTP_404_NOT_FOUND, str(e))
#     except Exception as e:
#         print(f"Error in update_club_status: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error updating club status: {str(e)}")

# @router.get("/clubs/{club_id}/analytics")
# async def get_club_analytics(
#     club_id: str,
#     date_from: Optional[datetime] = Query(None, description="Start date for analytics"),
#     date_to: Optional[datetime] = Query(None, description="End date for analytics"),
#     include_financials: bool = Query(True, description="Include financial data"),
#     include_activity: bool = Query(True, description="Include activity metrics"),
#     include_picks: bool = Query(True, description="Include pick history"),
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get comprehensive club analytics.
#     Admin-only access.
#     """
#     try:
#         # Validate date range
#         if date_from and date_to and date_to < date_from:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "date_to must be after date_from")
        
#         request = ClubAnalyticsRequest(
#             date_from=date_from,
#             date_to=date_to,
#             include_financials=include_financials,
#             include_activity=include_activity,
#             include_picks=include_picks
#         )
        
#         result = await admin_clubs_service.get_club_analytics(club_id, request)
#         return result
        
#     except ValueError as e:
#         raise HTTPException(HTTP_404_NOT_FOUND, str(e))
#     except Exception as e:
#         print(f"Error in get_club_analytics: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving club analytics: {str(e)}")

# @router.get("/clubs/{club_id}/performance")
# async def get_club_performance(
#     club_id: str,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get club performance metrics including win rate and ROI.
#     Admin-only access.
#     """
#     try:
#         result = await admin_clubs_service.get_club_performance(club_id)
#         return result
        
#     except ValueError as e:
#         raise HTTPException(HTTP_404_NOT_FOUND, str(e))
#     except Exception as e:
#         print(f"Error in get_club_performance: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving club performance: {str(e)}")

# @router.get("/clubs/{club_id}/activity-logs")
# async def get_club_activity_logs(
#     club_id: str,
#     page: int = Query(1, ge=1, description="Page number"),
#     limit: int = Query(50, ge=1, le=100, description="Items per page"),
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get activity logs for a specific club.
#     Admin-only access.
#     """
#     try:
#         result = await admin_clubs_service.get_club_activity_logs(club_id, page, limit)
#         return result
        
#     except ValueError as e:
#         raise HTTPException(HTTP_404_NOT_FOUND, str(e))
#     except Exception as e:
#         print(f"Error in get_club_activity_logs: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving club activity logs: {str(e)}")

# @router.post("/clubs/bulk-actions")
# async def perform_bulk_club_actions(
#     request: ClubBulkActionRequest,
#     admin_request: Request,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Perform bulk actions on multiple clubs (ban, suspend, reactivate).
#     Admin-only access.
#     """
#     try:
#         # Get client IP
#         client_ip = get_client_ip(admin_request)
        
#         result = await admin_clubs_service.perform_bulk_club_actions(request, token, client_ip)
#         return result
        
#     except Exception as e:
#         print(f"Error in perform_bulk_club_actions: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error performing bulk club actions: {str(e)}")

# # ========================================
# # Club & Owner CRUD Operations
# # ========================================

# @router.post("/clubs", response_model=ClubCreateResponse)
# async def create_club_with_owner(
#     request: ClubCreateRequest,
#     http_request: Request = None,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Create a new club with its owner in a single transaction.
    
#     This endpoint:
#     - Creates both club and owner simultaneously
#     - Validates uniqueness of club name and owner email
#     - Hashes owner password securely
#     - Creates initial club membership for owner
#     - Logs action for audit purposes
#     - Ensures transactional integrity
    
#     Admin-only access.
#     """
#     try:
#         # Get admin email from token (token is already validated and contains the email)
#         admin_email = token
        
#         # Get client IP address
#         ip_address = None
#         if http_request:
#             forwarded_for = http_request.headers.get("x-forwarded-for")
#             if forwarded_for:
#                 ip_address = forwarded_for.split(",")[0].strip()
#             else:
#                 ip_address = getattr(http_request.client, "host", None)
        
#         # Create club with owner
#         result = await admin_clubs_service.create_club_with_owner(request, admin_email, ip_address)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in create_club_with_owner: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in create_club_with_owner: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error creating club: {str(e)}")

# @router.put("/clubs/{club_id}", response_model=ClubUpdateResponse)
# async def update_club_with_owner(
#     club_id: str,
#     request: ClubUpdateRequest,
#     http_request: Request = None,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Update club details and optionally its owner information.
    
#     This endpoint:
#     - Updates club information (name, description, category, etc.)
#     - Optionally updates owner information (name, email, phone, password)
#     - Validates uniqueness constraints
#     - Tracks all changes for audit purposes
#     - Ensures transactional integrity
#     - Password is optional and only updated if provided
    
#     Admin-only access.
#     """
#     try:
#         # Validate club_id format
#         try:
#             ObjectId(club_id)
#         except:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid club ID format")
        
#         # Get admin email from token
#         # Token is already validated by get_current_admin dependency and contains the email
#         admin_email = token
        
#         # Get client IP address
#         ip_address = None
#         if http_request:
#             forwarded_for = http_request.headers.get("x-forwarded-for")
#             if forwarded_for:
#                 ip_address = forwarded_for.split(",")[0].strip()
#             else:
#                 ip_address = getattr(http_request.client, "host", None)
        
#         # Update club with owner
#         result = await admin_clubs_service.update_club_with_owner(club_id, request, admin_email, ip_address)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in update_club_with_owner: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in update_club_with_owner: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error updating club: {str(e)}")

@router.delete("/clubs/{club_id}", dependencies=[Depends(security_scheme)])
async def delete_club_with_owner(
    club_id: str,
    cascade_owner: bool = Query(False, description="Also soft delete the owner if they have no other clubs"),
    http_request: Request = None,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Soft delete a club and optionally its owner.
    
    This endpoint:
    - Performs soft deletion (sets is_deleted = true)
    - Deactivates all club memberships
    - Optionally deletes owner if cascade_owner=true and owner has no other clubs
    - Preserves data integrity with soft deletion
    - Logs action for audit purposes
    - Ensures transactional integrity
    - Sends email notifications to all club members
    
    Admin-only access.
    """
    try:
        # Validate club_id format
        try:
            ObjectId(club_id)
        except:
            return create_response(
                status_code=400,
                status="error",
                message="Invalid club ID format",
                data=None
            )
        
        # Get admin email from token
        admin_email = current_admin.get("email", "")
        
        # Get client IP address
        ip_address = None
        if http_request:
            forwarded_for = http_request.headers.get("x-forwarded-for")
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            else:
                ip_address = getattr(http_request.client, "host", None)
        
        # Delete club with optional owner cascade
        result = await admin_clubs_service.delete_club_with_owner(club_id, admin_email, ip_address, cascade_owner)
        
        return create_response(
            status_code=200,
            status="success",
            message="Club deleted successfully",
            data=result
        )
        
    except ValueError as ve:
        print(f"Validation error in delete_club_with_owner: {ve}")
        return create_response(
            status_code=400,
            status="error",
            message=str(ve),
            data=None
        )
    except Exception as e:
        print(f"Error in delete_club_with_owner: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error deleting club: {str(e)}",
            data=None
        )

# # ========================================
# # Moderator Management Routes
# # ========================================

# @router.get("/moderators", response_model=ModeratorListResponse)
# async def get_moderators_list(
#     # Basic search and legacy filters
#     search: Optional[str] = Query(None, description="Search by moderator name, email, or captain name"),
#     status: Optional[str] = Query(None, description="Filter by active/inactive status"),
#     club_id: Optional[str] = Query(None, description="Filter by assigned club ID"),
    
#     # Individual search filters (granular search control)
#     name: Optional[str] = Query(None, description="Search by moderator name (partial match)"),
#     email: Optional[str] = Query(None, description="Search by moderator email (partial match)"),
    
#     # Enhanced filters
#     club: Optional[str] = Query(None, description="Filter by club ID or name (partial match)"),
#     assigned_by: Optional[str] = Query(None, description="Filter by captain ID or name who assigned the moderator"),
    
#     # Sorting options
#     sort_by: Optional[str] = Query("date_joined", description="Field to sort by: name, date_joined, club_count, email, status"),
#     order: Optional[str] = Query("desc", description="Sort order: asc or desc"),
    
#     # Pagination
#     page: int = Query(1, ge=1, description="Page number for pagination"),
#     limit: int = Query(20, ge=1, le=100, description="Number of records per page"),
    
#     request: Request = None,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get comprehensive list of all moderators with enhanced filtering and sorting capabilities.
    
#     **Enhanced Features:**
#     - **Advanced Filtering**: Filter by club (ID or name), captain who assigned (ID or name), status
#     - **Dynamic Sorting**: Sort by name, date joined, club count, email, or status (asc/desc)
#     - **Partial Matching**: Club and captain filters support both ID and partial name matching
#     - **Combination Filters**: All filters can be used independently or together
#     - **Backward Compatibility**: Maintains all existing filter parameters
    
#     **Filter Parameters:**
#     - `name`: Search by moderator name (partial, case-insensitive)
#     - `email`: Search by moderator email (partial, case-insensitive)
#     - `club`: Filter by club ID or partial club name (case-insensitive)
#     - `assigned_by`: Filter by captain ID or partial captain name/email
#     - `status`: Filter by active/inactive moderator status
#     - `search`: Search across moderator names, emails, and captain details (legacy)
    
#     **Sorting Options:**
#     - `sort_by`: name, date_joined, club_count, email, status
#     - `order`: asc (ascending) or desc (descending)
#     - Default: date_joined DESC (newest first)
    
#     **Response Features:**
#     - Complete moderator profiles with contact information
#     - All club assignments with captain details and roles
#     - Pagination for large datasets with total counts
#     - Applied filters and sorting in response metadata
#     - Performance optimized with < 1 second response time
#     - Formatted dates in DD MMM YYYY format
#     - Graceful handling of missing data
    
#     **Examples:**
#     - `GET /admin/moderators?status=active&sort_by=name&order=asc`
#     - `GET /admin/moderators?name=John&email=example.com&sort_by=club_count&order=desc`
#     - `GET /admin/moderators?club=Sports&assigned_by=Captain&sort_by=name&order=asc`
#     - `GET /admin/moderators?name=Smith&club=Elite&status=active&page=2&limit=50`
    
#     Admin-only access required.
#     """
#     try:
#         # Get admin email (token is already validated and contains the email)
#         admin_email = token
        
#         # Get client IP address
#         ip_address = None
#         if request:
#             forwarded_for = request.headers.get("x-forwarded-for")
#             if forwarded_for:
#                 ip_address = forwarded_for.split(",")[0].strip()
#             else:
#                 ip_address = getattr(request.client, "host", None)
        
#         # Validate status parameter
#         parsed_status = None
#         if status:
#             valid_statuses = ["active", "inactive"]
#             if status.lower() not in valid_statuses:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid status. Must be one of: {valid_statuses}")
#             parsed_status = ModeratorStatus(status.lower())
        
#         # Validate club_id parameter (backward compatibility)
#         if club_id:
#             try:
#                 ObjectId(club_id)
#             except:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid club ID format")
        
#         # Validate sort_by parameter
#         valid_sort_fields = ["name", "date_joined", "club_count", "email", "status"]
#         if sort_by and sort_by not in valid_sort_fields:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid sort_by field. Must be one of: {valid_sort_fields}")
        
#         # Validate order parameter
#         valid_orders = ["asc", "desc"]
#         if order and order.lower() not in valid_orders:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid order. Must be one of: {valid_orders}")
        
#         # Parse sort_by and order to enums
#         from .models import ModeratorSortField, ModeratorSortOrder
#         parsed_sort_by = ModeratorSortField(sort_by) if sort_by else ModeratorSortField.DATE_JOINED
#         parsed_order = ModeratorSortOrder(order.lower()) if order else ModeratorSortOrder.DESC
        
#         # Create enhanced moderator list request
#         moderator_request = ModeratorListRequest(
#             search=search,
#             status=parsed_status,
#             club_id=club_id,
#             name=name,
#             email=email,
#             club=club,
#             assigned_by=assigned_by,
#             sort_by=parsed_sort_by,
#             order=parsed_order,
#             page=page,
#             limit=limit
#         )
        
#         # Get moderators list from service
#         result = await admin_moderators_service.get_moderators_list(
#             moderator_request, 
#             admin_email, 
#             ip_address
#         )
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in get_moderators_list: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in get_moderators_list: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving moderators: {str(e)}")

# ========================================
# Club Management Routes
# ========================================

@router.post("/clubs/{club_id}/approve", dependencies=[Depends(security_scheme)])
async def approve_club(
    club_id: str,
    approval_request: ClubApprovalRequest,
    request: Request = None,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Approve a club with email notification to the club owner.
    
    This endpoint allows admins to:
    - Approve pending clubs to make them live
    - Send automatic email notifications to club owners
    - Add internal admin notes for audit purposes
    - Track all approval actions with full audit trail
    
    Requirements:
    - Admin authentication required
    - Valid club ID (existing club)
    - Email notification optional but recommended
    
    The system will:
    - Update club status to 'approved' in database
    - Send professional email to club owner (if enabled)
    - Log the action with admin details and timestamps
    - Return comprehensive response with operation status
    """
    try:
        # Get admin email from token
        admin_email = current_admin.get("email", "")
        
        # Get client IP address for audit logging
        ip_address = None
        if request:
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            else:
                ip_address = getattr(request.client, "host", None)
        print("club_id","club_id",club_id)
        # Validate club ID format
        try:
            ObjectId(club_id)
        except:
            return create_response(
                status_code=400,
                status="error",
                message="Invalid club ID format",
                data=None
            )
        
        # Set status to approved
        approval_request.status = ClubApprovalStatus.APPROVED
        
        # Process approval
        result = await admin_club_management_service.approve_reject_club(
            club_id=club_id,
            request=approval_request,
            admin_email=admin_email,
            ip_address=ip_address
        )
        
        if not result.success:
            return create_response(
                status_code=400,
                status="error",
                message=result.message,
                data=None
            )
        
        # Convert result to serializable format
        result_data = {
            "success": result.success,
            "message": result.message,
            "club_id": result.club_id,
            "previous_status": result.previous_status,
            "new_status": result.new_status,
            "notification_sent": result.notification_sent,
            "owner_email": result.owner_email,
            "admin_email": result.admin_email,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None,
            "approval_id": result.approval_id
        }
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Club approved successfully",
            data=result_data
        )
        
    except ValueError as ve:
        print(f"Validation error in approve_club: {ve}")
        return create_response(
            status_code=400,
            status="error",
            message=str(ve),
            data=None
        )
    except Exception as e:
        print(f"Error in approve_club: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error processing club approval: {str(e)}",
            data=None
        )

@router.post("/clubs/{club_id}/reject", dependencies=[Depends(security_scheme)])
async def reject_club(
    club_id: str,
    approval_request: ClubApprovalRequest,
    request: Request = None,
    current_admin: dict = Depends(get_current_admin)
):
    """
    Reject a club with email notification to the club owner.
    
    This endpoint allows admins to:
    - Reject pending clubs with temporary or permanent rejection
    - Send automatic email notifications to club owners
    - Process refunds for permanent rejections
    - Add internal admin notes for audit purposes
    - Track all rejection actions with full audit trail
    
    **Rejection Types:**
    - **Temporary Rejection**: Club status becomes "rejected", captain can edit and resubmit
    - **Permanent Rejection**: Club is deleted, refund is processed to captain
    
    **Requirements:**
    - Admin authentication required
    - Valid club ID (existing club)
    - Rejection requires a reason
    - Email notification optional but recommended
    
    **Request Body:**
    - `rejection_type`: "temporary" or "permanent"
    - `reason`: Mandatory reason for rejection
    - `refund_amount`: Amount to refund (optional - system automatically finds and refunds all payments)
    - `notify_owner`: Send email notification (default: true)
    - `admin_notes`: Internal admin notes
    
    **The system will:**
    - Update club status based on rejection type
    - Send appropriate email to club owner (if enabled)
    - **Automatically find and refund all payments** made during pending stage for permanent rejections
    - **Cancel unconfirmed payments** and **refund confirmed payments** via Stripe
    - Log the action with admin details and timestamps
    - Return comprehensive response with operation status
    """
    try:
        # Get admin email from token
        admin_email = current_admin.get("email", "")
        
        # Get client IP address for audit logging
        ip_address = None
        if request:
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            else:
                ip_address = getattr(request.client, "host", None)
        
        # Validate club ID format
        try:
            ObjectId(club_id)
        except:
            return create_response(
                status_code=400,
                status="error",
                message="Invalid club ID format",
                data=None
            )
        
        # Validate that reason is provided for rejection
        if not approval_request.reason:
            return create_response(
                status_code=400,
                status="error",
                message="Reason is required for club rejection",
                data=None
            )
        
        # Determine rejection status based on rejection_type
        if approval_request.rejection_type == "temporary":
            approval_request.status = ClubApprovalStatus.REJECTED_TEMPORARY
        elif approval_request.rejection_type == "permanent":
            approval_request.status = ClubApprovalStatus.REJECTED_PERMANENT
        else:
            # Default to permanent rejection for backward compatibility
            approval_request.status = ClubApprovalStatus.REJECTED_PERMANENT
            approval_request.rejection_type = "permanent"
        
        # Process rejection
        result = await admin_club_management_service.approve_reject_club(
            club_id=club_id,
            request=approval_request,
            admin_email=admin_email,
            ip_address=ip_address
        )
        
        if not result.success:
            return create_response(
                status_code=400,
                status="error",
                message=result.message,
                data=None
            )
        
        # Convert result to serializable format
        result_data = {
            "success": result.success,
            "message": result.message,
            "club_id": result.club_id,
            "previous_status": result.previous_status,
            "new_status": result.new_status,
            "notification_sent": result.notification_sent,
            "owner_email": result.owner_email,
            "admin_email": result.admin_email,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None,
            "approval_id": result.approval_id,
            "rejection_type": result.rejection_type,
            "refund_amount": result.refund_amount,
            "is_resubmit": result.is_resubmit,
            "is_club_reject_permanently": result.is_club_reject_permanently,
            "is_club_reject_temporary": result.is_club_reject_temporary
        }
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Club rejected successfully",
            data=result_data
        )
        
    except ValueError as ve:
        print(f"Validation error in reject_club: {ve}")
        return create_response(
            status_code=400,
            status="error",
            message=str(ve),
            data=None
        )
    except Exception as e:
        print(f"Error in reject_club: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error processing club rejection: {str(e)}",
            data=None
        )

# @router.get("/clubs/{club_id}/monitor", response_model=ClubMonitoringResponse)
# async def get_club_monitoring_data(
#     club_id: str,
#     period: str = Query("weekly", description="Monitoring period: daily, weekly, monthly"),
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get comprehensive club monitoring data including activity metrics and health status.
    
#     This endpoint provides detailed insights into club performance:
    
#     **Activity Metrics:**
#     - Messages sent by members
#     - Betting picks posted
#     - New member acquisitions
#     - Member engagement rates
#     - Average daily activity levels
#     - Last activity tracking
#     - Inactive status detection (7+ days without activity)
    
#     **Performance Summary:**
#     - Pick performance statistics (win/loss rates)
#     - Profit/loss tracking
#     - Win streaks and performance trends
#     - ROI calculations
    
#     **Health Status:**
#     - Overall health score (0-100)
#     - Identified issues and red flags
#     - Actionable recommendations for improvement
#     - Health status flags for quick assessment
    
#     **Monitoring Periods:**
#     - Daily: Last 24 hours of activity
#     - Weekly: Last 7 days of activity (default)
#     - Monthly: Last 30 days of activity
    
#     **Use Cases:**
#     - Identify underperforming clubs requiring intervention
#     - Monitor club health and engagement levels
#     - Track pick performance and profitability
#     - Generate reports for club owner guidance
#     - Detect inactive clubs for outreach campaigns
    
#     Admin-only access with full audit logging.
#     """
#     try:
#         # Validate club ID format
#         try:
#             ObjectId(club_id)
#         except:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid club ID format")
        
#         # Validate period parameter
#         valid_periods = ["daily", "weekly", "monthly"]
#         if period.lower() not in valid_periods:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid period. Must be one of: {valid_periods}")
        
#         activity_period = ActivityPeriod(period.lower())
        
#         # Get monitoring data
#         result = await admin_club_management_service.get_club_monitoring_data(
#             club_id=club_id,
#             period=activity_period
#         )
        
#         if not result.success:
#             raise HTTPException(HTTP_404_NOT_FOUND if "not found" in result.message.lower() else HTTP_400_BAD_REQUEST, result.message)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in get_club_monitoring_data: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in get_club_monitoring_data: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving monitoring data: {str(e)}")

# @router.get("/clubs/{club_id}/picks", response_model=ClubPicksResponse)
# async def get_club_picks(
#     club_id: str,
#     status: Optional[str] = Query(None, description="Filter by pick status"),
#     pick_type: Optional[str] = Query(None, description="Filter by pick type"),
#     submitted_by_role: Optional[str] = Query(None, description="Filter by submitter role"),
#     sport: Optional[str] = Query(None, description="Filter by sport"),
#     date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
#     date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
#     search: Optional[str] = Query(None, description="Search pick titles and descriptions"),
#     page: int = Query(1, ge=1, description="Page number"),
#     limit: int = Query(20, ge=1, le=100, description="Records per page"),
#     sort_by: str = Query("date_submitted", description="Sort field"),
#     sort_order: str = Query("desc", description="Sort order (asc/desc)"),
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get comprehensive list of club picks with advanced filtering and search capabilities.
    
#     This endpoint provides complete access to club betting picks data:
    
#     **Pick Information:**
#     - Pick title and detailed description
#     - Pick type (single, parlay, teaser, prop, live)
#     - Sport and game details
#     - Odds and stake information
#     - Potential payout calculations
#     - Confidence levels (1-10 scale)
    
#     **Submitter Details:**
#     - Full name and email of pick submitter
#     - Role (captain, moderator, analyst, editor)
#     - Submission timestamp with precise formatting
    
#     **Pick Status Tracking:**
#     - Current status (pending, won, lost, cancelled, void)
#     - Outcome dates and results
#     - Profit/loss calculations
#     - Performance tracking
    
#     **Advanced Filtering:**
#     - Status: Filter by pick outcome status
#     - Type: Filter by pick type (single, parlay, etc.)
#     - Role: Filter by submitter role
#     - Sport: Filter by specific sport
#     - Date Range: Custom date range filtering
#     - Search: Full-text search across titles and descriptions
    
#     **Sorting Options:**
#     - Date submitted (default, newest first)
#     - Pick title (alphabetical)
#     - Status (grouped by outcome)
#     - Odds (highest/lowest first)
#     - Profit/loss (best/worst performance)
    
#     **Summary Statistics:**
#     - Total picks and status breakdown
#     - Win rate and performance metrics
#     - Total profit/loss calculations
#     - Average odds across picks
#     - Most active pick contributor
    
#     **Pagination:**
#     - Efficient pagination for large datasets
#     - Configurable page sizes (1-100 records)
#     - Complete pagination metadata
    
#     Perfect for:
#     - Pick performance analysis
#     - Contributor activity monitoring
#     - Club profitability assessment
#     - Historical pick research
#     - Member engagement tracking
    
#     Admin-only access with comprehensive audit logging.
#     """
#     try:
#         # Validate club ID format
#         try:
#             ObjectId(club_id)
#         except:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid club ID format")
        
#         # Validate and parse sort_order
#         try:
#             sort_order_enum = SortOrder(sort_order.lower())
#         except ValueError:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid sort_order. Must be 'asc' or 'desc'")
        
#         # Create picks request object
#         picks_request = ClubPicksRequest(
#             status=status,
#             pick_type=pick_type,
#             submitted_by_role=submitted_by_role,
#             sport=sport,
#             date_from=date_from,
#             date_to=date_to,
#             search=search,
#             page=page,
#             limit=limit,
#             sort_by=sort_by,
#             sort_order=sort_order_enum
#         )
        
#         # Get picks data
#         result = await admin_club_management_service.get_club_picks(
#             club_id=club_id,
#             request=picks_request
#         )
        
#         if not result.success:
#             raise HTTPException(HTTP_404_NOT_FOUND if "not found" in result.message.lower() else HTTP_400_BAD_REQUEST, result.message)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in get_club_picks: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in get_club_picks: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving club picks: {str(e)}")

# # ========================================
# # Moderator Details Route
# # ========================================

# @router.get("/moderators/{moderator_id}", response_model=ModeratorDetailsResponse)
# async def get_moderator_details(
#     moderator_id: str,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get comprehensive details of a specific moderator for admin oversight.
    
#     This endpoint provides complete moderator information including:
    
#     **Profile Information:**
#     - Full name, email, phone number
#     - Account creation date and status
#     - Avatar/profile picture URL
#     - Last login information
    
#     **Club Assignments:**
#     - All clubs where moderator is assigned
#     - Role in each club (moderator, analyst, editor)
#     - Captain details who assigned the moderator
#     - Assignment dates and subscription status
    
#     **Submitted Picks:**
#     - Complete pick history with outcomes
#     - Game details, odds, stakes, and profit/loss
#     - Pick types and confidence levels
#     - Tagged picks and submission dates
#     - Club context for each pick
    
#     **Locker Room Actions:**
#     - All moderation actions performed
#     - Action types (mute, ban, delete, warn, etc.)
#     - Target users and reasons for actions
#     - Duration for temporary actions
#     - Club context and action dates
    
#     **Win/Loss Statistics:**
#     - Total picks and outcome breakdown
#     - Win rate and loss rate percentages
#     - Profit/loss calculations and ROI
#     - Best and current win streaks
#     - Average odds and total stakes
    
#     **Data Formatting:**
#     - All dates in DD MMM YYYY format
#     - Date-times in DD MMM YYYY HH:mm format
#     - Empty arrays for missing data (never null)
#     - Graceful handling of incomplete records
    
#     **Security & Validation:**
#     - Admin-only access with JWT validation
#     - Moderator role verification
#     - Input validation for moderator ID format
#     - Comprehensive error handling
    
#     **Use Cases:**
#     - Administrative oversight and monitoring
#     - Performance review and analytics
#     - Compliance and audit requirements
#     - Moderator activity assessment
#     - Data export for reporting
    
#     **Response Time:** < 1 second for standard requests
#     **Error Handling:** Comprehensive with specific error codes
#     **Data Integrity:** Complete validation and consistency checks
#     """
#     try:
#         # Validate moderator_id format
#         try:
#             ObjectId(moderator_id)
#         except:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid moderator ID format")
        
#         # Get comprehensive moderator details
#         result = await admin_moderator_details_service.get_moderator_details(moderator_id)
        
#         # Handle specific error cases
#         if not result.success:
#             if result.error_code == "NOT_FOUND":
#                 raise HTTPException(HTTP_404_NOT_FOUND, result.message)
#             elif result.error_code == "INVALID_ID":
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
#             elif result.error_code == "NOT_MODERATOR":
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
#             else:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in get_moderator_details: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in get_moderator_details: {e}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, f"Error retrieving moderator details: {str(e)}")

# # ========================================
# # Moderator Management Routes (CRUD with Captain Approval)
# # ========================================

# @router.post("/moderators", response_model=ModeratorCreateResponse)
# async def create_moderator(
#     request: ModeratorCreateRequest,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Create a new moderator with Captain request approval validation.
    
#     **Required Captain Approval:**
#     - Must have an approved Captain request with matching `request_id`
#     - Request must be of type "add" and status "approved"
#     - Request must be recent (within 24 hours)
    
#     **Features:**
#     - **Approval Dependency**: Only approved Captain requests allowed
#     - **Email Uniqueness**: Validates email is unique among moderators
#     - **Club Validation**: Ensures all assigned clubs exist and are active
#     - **Atomic Operations**: User and club memberships created together
#     - **Audit Logging**: Complete action logging for compliance
#     - **Role Assignment**: Supports multiple moderator roles
    
#     **Request Body:**
#     ```json
#     {
#       "request_id": "REQ_001_ADD_MOD_2025",
#       "moderator_name": "John Smith",
#       "email": "john.smith@example.com",
#       "phone": "+1234567890",
#       "assigned_clubs": ["64f7b1234567890abcdef123", "64f7b1234567890abcdef124"],
#       "roles": ["chat_moderator", "pick_poster"]
#     }
#     ```
    
#     **Success Response:**
#     - Moderator created with all club assignments
#     - Complete moderator profile returned
#     - Action logged with Captain and Admin details
    
#     **Error Responses:**
#     - **403**: Captain request not approved or expired
#     - **404**: Captain request not found
#     - **409**: Email already in use
#     - **400**: Invalid club IDs or validation errors
    
#     **Security:**
#     - Admin-only access with JWT validation
#     - All inputs validated and sanitized
#     - Captain request dependency enforced
    
#     Admin-only access required.
#     """
#     try:
#         # Get admin details from token
#         admin_email = token
        
#         # Get admin ID from database
#         admin_user = await admin_collection.find_one({"email": admin_email})
#         if not admin_user:
#             raise HTTPException(HTTP_401_UNAUTHORIZED, "Admin user not found")
        
#         admin_id = str(admin_user["_id"])
        
#         print(f"🚀 Admin {admin_email} creating moderator with request {request.request_id}")
        
#         # Create moderator via service
#         result = await admin_moderator_management_service.create_moderator(
#             request, admin_email, admin_id
#         )
        
#         if not result.success:
#             if "not approved" in result.message or "expired" in result.message:
#                 raise HTTPException(HTTP_403_FORBIDDEN, result.message)
#             elif "already in use" in result.message:
#                 raise HTTPException(HTTP_409_CONFLICT, result.message)
#             elif "Invalid club" in result.message:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
#             else:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in create_moderator: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in create_moderator: {e}")
#         raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to create moderator: {str(e)}")

# @router.put("/moderators/{moderator_id}", response_model=ModeratorUpdateResponse)
# async def update_moderator(
#     moderator_id: str,
#     request: ModeratorUpdateRequest,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Update an existing moderator with Captain request approval validation.
    
#     **Required Captain Approval:**
#     - Must have an approved Captain request with matching `request_id`
#     - Request must be of type "edit" and status "approved"
#     - Request must include the moderator ID being updated
#     - Request must be recent (within 24 hours)
    
#     **Features:**
#     - **Approval Dependency**: Only approved Captain requests allowed
#     - **Partial Updates**: Only provided fields are updated
#     - **Email Uniqueness**: Validates email uniqueness (excluding current moderator)
#     - **Club Reassignment**: Atomic club membership updates
#     - **Change Tracking**: Detailed logging of all changes made
#     - **Role Updates**: Supports updating moderator roles
    
#     **Path Parameters:**
#     - `moderator_id`: ID of moderator to update
    
#     **Request Body (all fields optional):**
#     ```json
#     {
#       "request_id": "REQ_001_EDIT_MOD_2025",
#       "moderator_name": "John David Smith",
#       "email": "john.d.smith@example.com",
#       "phone": "+1234567891",
#       "assigned_clubs": ["64f7b1234567890abcdef125"],
#       "roles": ["chat_moderator", "content_reviewer"]
#     }
#     ```
    
#     **Success Response:**
#     - Updated moderator profile returned
#     - List of changes made included
#     - Action logged with before/after values
    
#     **Error Responses:**
#     - **403**: Captain request not approved or expired
#     - **404**: Moderator or Captain request not found
#     - **409**: Email already in use by another moderator
#     - **400**: Invalid club IDs or validation errors
    
#     **Security:**
#     - Admin-only access with JWT validation
#     - Moderator existence validated
#     - Captain request dependency enforced
    
#     Admin-only access required.
#     """
#     try:
#         # Validate moderator ID format
#         try:
#             ObjectId(moderator_id)
#         except:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid moderator ID format")
        
#         # Get admin details from token
#         admin_email = token
        
#         # Get admin ID from database
#         admin_user = await admin_collection.find_one({"email": admin_email})
#         if not admin_user:
#             raise HTTPException(HTTP_401_UNAUTHORIZED, "Admin user not found")
        
#         admin_id = str(admin_user["_id"])
        
#         print(f"🔄 Admin {admin_email} updating moderator {moderator_id} with request {request.request_id}")
        
#         # Update moderator via service
#         result = await admin_moderator_management_service.update_moderator(
#             moderator_id, request, admin_email, admin_id
#         )
        
#         if not result.success:
#             if "not found" in result.message:
#                 raise HTTPException(HTTP_404_NOT_FOUND, result.message)
#             elif "not approved" in result.message or "expired" in result.message:
#                 raise HTTPException(HTTP_403_FORBIDDEN, result.message)
#             elif "already in use" in result.message:
#                 raise HTTPException(HTTP_409_CONFLICT, result.message)
#             elif "Invalid club" in result.message:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
#             else:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in update_moderator: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in update_moderator: {e}")
#         raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to update moderator: {str(e)}")

# @router.delete("/moderators/{moderator_id}", response_model=ModeratorDeleteResponse)
# async def delete_moderator(
#     moderator_id: str,
#     request: ModeratorDeleteRequest,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Delete (soft delete) a moderator with Captain request approval validation.
    
#     **Required Captain Approval:**
#     - Must have an approved Captain request with matching `request_id`
#     - Request must be of type "delete" and status "approved"
#     - Request must include the moderator ID being deleted
#     - Request must be recent (within 24 hours)
    
#     **Features:**
#     - **Approval Dependency**: Only approved Captain requests allowed
#     - **Soft Delete**: Moderator marked as deleted, not removed
#     - **Membership Cleanup**: All club memberships deactivated
#     - **Data Preservation**: Historical data maintained for auditing
#     - **Complete Logging**: Deletion reason and details logged
    
#     **Path Parameters:**
#     - `moderator_id`: ID of moderator to delete
    
#     **Request Body:**
#     ```json
#     {
#       "request_id": "REQ_001_DELETE_MOD_2025",
#       "delete_reason": "Voluntary resignation from all moderation duties"
#     }
#     ```
    
#     **Success Response:**
#     - Deletion confirmation with moderator ID
#     - Action logged with deletion details
#     - All memberships deactivated
    
#     **Error Responses:**
#     - **403**: Captain request not approved or expired
#     - **404**: Moderator or Captain request not found
#     - **400**: Invalid moderator ID format
    
#     **Security:**
#     - Admin-only access with JWT validation
#     - Moderator existence validated
#     - Captain request dependency enforced
#     - Soft delete preserves audit trail
    
#     **Note:**
#     This is a soft delete operation. The moderator account is marked as deleted
#     and deactivated, but historical data is preserved for compliance and auditing.
    
#     Admin-only access required.
#     """
#     try:
#         # Validate moderator ID format
#         try:
#             ObjectId(moderator_id)
#         except:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid moderator ID format")
        
#         # Get admin details from token
#         admin_email = token
        
#         # Get admin ID from database
#         admin_user = await admin_collection.find_one({"email": admin_email})
#         if not admin_user:
#             raise HTTPException(HTTP_401_UNAUTHORIZED, "Admin user not found")
        
#         admin_id = str(admin_user["_id"])
        
#         print(f"🗑️ Admin {admin_email} deleting moderator {moderator_id} with request {request.request_id}")
        
#         # Delete moderator via service
#         result = await admin_moderator_management_service.delete_moderator(
#             moderator_id, request, admin_email, admin_id
#         )
        
#         if not result.success:
#             if "not found" in result.message:
#                 raise HTTPException(HTTP_404_NOT_FOUND, result.message)
#             elif "not approved" in result.message or "expired" in result.message:
#                 raise HTTPException(HTTP_403_FORBIDDEN, result.message)
#             else:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in delete_moderator: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in delete_moderator: {e}")
#         raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to delete moderator: {str(e)}")

# # ========================================
# # Captain Request Management Routes (Request Submission & Approval)
# # ========================================

# @router.post("/captain/moderator-requests", response_model=CaptainRequestSubmissionResponse)
# async def submit_captain_moderator_request(
#     request: CaptainModeratorRequestSubmission,
#     token: str = Depends(get_current_admin)  # For now, using admin auth - can be changed to captain auth
# ):
#     """
#     Submit a Captain request for moderator action (add/edit/delete).
    
#     **This endpoint generates the `request_id` needed for moderator CRUD operations.**
    
#     **Workflow:**
#     1. Captain submits request → Gets `request_id`
#     2. Admin approves request → `request_id` becomes valid
#     3. Admin uses `request_id` → Performs moderator action
    
#     **Request Types:**
#     - **Add Moderator**: Requires `moderator_data` with new moderator details
#     - **Edit Moderator**: Requires `moderator_id` and `moderator_data` with changes  
#     - **Delete Moderator**: Requires `moderator_id` only
    
#     **Request Body Examples:**
    
#     **Add Moderator Request:**
#     ```json
#     {
#       "action_type": "add",
#       "moderator_data": {
#         "moderator_name": "John Smith",
#         "email": "john.smith@example.com",
#         "phone": "+1234567890",
#         "assigned_clubs": ["64f7b1234567890abcdef123"],
#         "roles": ["chat_moderator", "pick_poster"]
#       },
#       "request_reason": "We need additional moderator support for increased club activity during peak hours",
#       "club_id": "64f7b1234567890abcdef123"
#     }
#     ```
    
#     **Edit Moderator Request:**
#     ```json
#     {
#       "action_type": "edit",
#       "moderator_id": "64f7b1234567890abcdef789",
#       "moderator_data": {
#         "moderator_name": "John David Smith",
#         "email": "john.d.smith@example.com",
#         "assigned_clubs": ["64f7b1234567890abcdef123", "64f7b1234567890abcdef124"],
#         "roles": ["chat_moderator", "content_reviewer"]
#       },
#       "request_reason": "Updating moderator details and expanding role to content review",
#       "club_id": "64f7b1234567890abcdef123"
#     }
#     ```
    
#     **Delete Moderator Request:**
#     ```json
#     {
#       "action_type": "delete", 
#       "moderator_id": "64f7b1234567890abcdef789",
#       "request_reason": "Moderator has requested to step down from all moderation duties",
#       "club_id": "64f7b1234567890abcdef123"
#     }
#     ```
    
#     **Success Response:**
#     - Unique `request_id` generated for tracking
#     - Request status set to "pending" 
#     - Captain and club details recorded
#     - Timestamp recorded for audit trail
    
#     **Generated `request_id` Format:**
#     `REQ_ADD_20250125_143000_C456_ABC123`
#     - Action type (ADD/EDIT/DELETE)
#     - Timestamp
#     - Captain ID suffix
#     - Unique identifier
    
#     **Validation:**
#     - Captain must exist and have access to the specified club
#     - Moderator ID must exist for edit/delete actions
#     - Required fields validated based on action type
#     - Club ID must be valid and accessible to captain
    
#     **Next Steps:**
#     1. Use the returned `request_id` to track request status
#     2. Admin reviews and approves the request
#     3. Admin uses the `request_id` in moderator CRUD APIs
    
#     Currently using admin authentication for testing.
#     """
#     try:
#         # Get captain details from token (using admin for now)
#         captain_email = token
        
#         # Get captain ID from database (using admin collection for now)
#         captain_user = await admin_collection.find_one({"email": captain_email})
#         if not captain_user:
#             raise HTTPException(HTTP_401_UNAUTHORIZED, "Captain user not found")
        
#         captain_id = str(captain_user["_id"])
        
#         print(f"📝 Captain {captain_email} submitting {request.action_type.value} request for club {request.club_id}")
        
#         # Submit request via service
#         result = await admin_captain_request_service.submit_captain_request(
#             request, captain_id, captain_email
#         )
        
#         if not result.success:
#             if "not found" in result.message or "access" in result.message:
#                 raise HTTPException(HTTP_404_NOT_FOUND, result.message)
#             else:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in submit_captain_moderator_request: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in submit_captain_moderator_request: {e}")
#         raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to submit request: {str(e)}")

# @router.post("/moderator-requests/{request_id}/approve", response_model=AdminRequestApprovalResponse)
# async def approve_reject_moderator_request(
#     request_id: str,
#     approval_request: AdminRequestApprovalRequest,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Approve or reject a Captain moderator request.
    
#     **This endpoint makes the `request_id` valid for moderator CRUD operations.**
    
#     **Actions:**
#     - **approve**: Makes the request_id valid for 24 hours
#     - **reject**: Permanently rejects the request with reason
    
#     **Path Parameters:**
#     - `request_id`: The request ID to approve/reject
    
#     **Request Body:**
#     ```json
#     {
#       "action": "approve",
#       "admin_notes": "Request approved - moderator needed for weekend coverage"
#     }
#     ```
    
#     **Or for rejection:**
#     ```json
#     {
#       "action": "reject",
#       "admin_notes": "Insufficient justification provided",
#       "rejection_reason": "The request reason does not provide adequate justification for adding a new moderator at this time"
#     }
#     ```
    
#     **Success Response:**
#     - Request status updated to "approved" or "rejected"
#     - Admin details recorded for audit trail
#     - Approval timestamp set for tracking
#     - Complete request data returned
    
#     **After Approval:**
#     The `request_id` can now be used in moderator CRUD operations:
#     - `POST /admin/moderators` (for add requests)
#     - `PUT /admin/moderators/{id}` (for edit requests)  
#     - `DELETE /admin/moderators/{id}` (for delete requests)
    
#     **Request Expiration:**
#     Approved requests are valid for 24 hours from approval time.
    
#     **Error Responses:**
#     - **404**: Request not found
#     - **400**: Request already processed
#     - **400**: Invalid action or missing rejection reason
    
#     Admin-only access required.
#     """
#     try:
#         # Get admin details from token
#         admin_email = token
        
#         # Get admin ID from database
#         admin_user = await admin_collection.find_one({"email": admin_email})
#         if not admin_user:
#             raise HTTPException(HTTP_401_UNAUTHORIZED, "Admin user not found")
        
#         admin_id = str(admin_user["_id"])
        
#         print(f"⚖️ Admin {admin_email} {approval_request.action}ing request {request_id}")
        
#         # Process approval/rejection via service
#         result = await admin_captain_request_service.approve_reject_request(
#             request_id, approval_request, admin_id, admin_email
#         )
        
#         if not result.success:
#             if "not found" in result.message:
#                 raise HTTPException(HTTP_404_NOT_FOUND, result.message)
#             elif "already been" in result.message:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
#             else:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in approve_reject_moderator_request: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in approve_reject_moderator_request: {e}")
#         raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to process request: {str(e)}")

# @router.get("/moderator-requests", response_model=CaptainRequestListResponse)
# async def get_moderator_requests_list(
#     status: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected"),
#     action_type: Optional[str] = Query(None, description="Filter by action: add, edit, delete"),
#     captain_id: Optional[str] = Query(None, description="Filter by captain ID"),
#     club_id: Optional[str] = Query(None, description="Filter by club ID"),
#     date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
#     date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
#     page: int = Query(1, ge=1, description="Page number for pagination"),
#     limit: int = Query(20, ge=1, le=100, description="Number of records per page"),
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get list of Captain moderator requests with filtering and pagination.
    
#     **Features:**
#     - **Complete Request History**: All submitted requests with details
#     - **Status Filtering**: Filter by pending, approved, rejected
#     - **Action Filtering**: Filter by add, edit, delete requests
#     - **Captain/Club Filtering**: Filter by specific captain or club
#     - **Date Range Filtering**: Filter by submission date range
#     - **Pagination**: Efficient pagination for large datasets
#     - **Status Counts**: Summary counts by request status
    
#     **Query Parameters (all optional):**
#     - `status`: pending, approved, rejected
#     - `action_type`: add, edit, delete
#     - `captain_id`: Filter by specific captain
#     - `club_id`: Filter by specific club
#     - `date_from`: Start date (YYYY-MM-DD)
#     - `date_to`: End date (YYYY-MM-DD)
#     - `page`: Page number (default: 1)
#     - `limit`: Records per page (default: 20, max: 100)
    
#     **Response Features:**
#     - Complete request details with captain and club information
#     - Approval/rejection details with admin information
#     - Status counts for dashboard metrics
#     - Applied filters summary
#     - Pagination metadata
    
#     **Use Cases:**
#     - **Admin Dashboard**: Monitor all pending requests
#     - **Request History**: Review completed requests
#     - **Captain Activity**: Track specific captain's requests
#     - **Club Management**: View club-specific requests
#     - **Audit Trail**: Complete request history with approvals
    
#     **Example Requests:**
#     ```
#     # Get all pending requests
#     GET /admin/moderator-requests?status=pending
    
#     # Get requests for specific club
#     GET /admin/moderator-requests?club_id=64f7b1234567890abcdef123
    
#     # Get requests from date range
#     GET /admin/moderator-requests?date_from=2025-01-01&date_to=2025-01-31
    
#     # Get approved add requests
#     GET /admin/moderator-requests?status=approved&action_type=add
#     ```
    
#     **Response includes:**
#     - Request details (ID, type, reason, status)
#     - Captain information (ID, name)
#     - Club information (ID, name)
#     - Approval details (admin, timestamp, notes)
#     - Status summary counts
#     - Pagination information
    
#     Admin-only access required.
#     """
#     try:
#         # Get admin email from token
#         admin_email = token
        
#         print(f"📋 Admin {admin_email} requesting moderator requests list")
        
#         # Validate and parse status
#         parsed_status = None
#         if status:
#             from .models import ModeratorRequestStatus
#             valid_statuses = [s.value for s in ModeratorRequestStatus]
#             if status not in valid_statuses:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid status. Must be one of: {valid_statuses}")
#             parsed_status = ModeratorRequestStatus(status)
        
#         # Validate and parse action_type
#         parsed_action_type = None
#         if action_type:
#             from .models import ModeratorActionType
#             valid_actions = [a.value for a in ModeratorActionType]
#             if action_type not in valid_actions:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid action_type. Must be one of: {valid_actions}")
#             parsed_action_type = ModeratorActionType(action_type)
        
#         # Validate object IDs
#         if captain_id:
#             try:
#                 ObjectId(captain_id)
#             except:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid captain_id format")
        
#         if club_id:
#             try:
#                 ObjectId(club_id)
#             except:
#                 raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid club_id format")
        
#         # Create request object
#         list_request = CaptainRequestListRequest(
#             status=parsed_status,
#             action_type=parsed_action_type,
#             captain_id=captain_id,
#             club_id=club_id,
#             date_from=date_from,
#             date_to=date_to,
#             page=page,
#             limit=limit
#         )
        
#         # Get requests list from service
#         result = await admin_captain_request_service.get_requests_list(
#             list_request, admin_email
#         )
        
#         if not result.success:
#             raise HTTPException(HTTP_400_BAD_REQUEST, result.message)
        
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in get_moderator_requests_list: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in get_moderator_requests_list: {e}")

# # ========================================
# # SUBSCRIPTION PLANS MANAGEMENT ROUTES
# # ========================================

# @router.get("/subscription-plans", response_model=SubscriptionPlanListResponse)
# async def get_subscription_plans_list(
#     search: Optional[str] = Query(None, description="Search by name or type"),
#     type: Optional[str] = Query(None, description="Filter by plan type (Trial, Monthly Club Membership, Club Ownership, Premium Membership, Basic Membership, VIP Membership)"),
#     is_active: Optional[bool] = Query(None, description="Filter by active status"),
#     price_min: Optional[float] = Query(None, ge=0, description="Minimum price filter"),
#     price_max: Optional[float] = Query(None, ge=0, description="Maximum price filter"),
#     sort_by: str = Query("name", description="Field to sort by"),
#     sort_order: str = Query("asc", description="Sort order (asc/desc)"),
#     page: int = Query(1, ge=1, description="Page number"),
#     limit: int = Query(20, ge=1, le=100, description="Items per page"),
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Get paginated, searchable, and sortable list of subscription plans with active subscriber counts
    
#     **Features:**
#     - **Pagination**: Configurable page size and navigation
#     - **Search**: Case-insensitive search by name or type
#     - **Filtering**: By type, active status, and price range
#     - **Sorting**: By name, type, price, active subscribers, created/updated dates
#     - **Active Subscriber Count**: Real-time calculation from subscriptions collection
#     - **Summary Statistics**: Total plans, active plans, total subscribers, revenue potential
    
#     **Query Parameters:**
#     - `search`: Search term for name or type (case-insensitive)
#     - `type`: Filter by specific plan type
#     - `is_active`: Filter by active status (true/false)
#     - `price_min`/`price_max`: Price range filtering
#     - `sort_by`: Field to sort by (name, type, price, active_subscribers, created_at, updated_at)
#     - `sort_order`: Sort direction (asc/desc)
#     - `page`: Page number (default: 1)
#     - `limit`: Items per page (default: 20, max: 100)
    
#     **Response includes:**
#     - List of subscription plans with active subscriber counts
#     - Pagination information (current page, total pages, has next/previous)
#     - Applied filters summary
#     - Summary statistics (total plans, active plans, total subscribers, revenue potential)
    
#     **Example Usage:**
#     ```
#     # Get all active plans sorted by price
#     GET /admin/subscription-plans?is_active=true&sort_by=price&sort_order=asc
    
#     # Search for trial plans
#     GET /admin/subscription-plans?search=trial&type=Trial
    
#     # Get plans in price range
#     GET /admin/subscription-plans?price_min=10&price_max=50
    
#     # Get plans with pagination
#     GET /admin/subscription-plans?page=2&limit=10
#     ```
    
#     Admin-only access required.
#     """
#     try:
#         print(f"🔍 Processing subscription plans request - type: {type}, search: {search}, is_active: {is_active}")
        
#         # Validate sort_by field
#         valid_sort_fields = ["name", "type", "price", "active_subscribers", "created_at", "updated_at"]
#         if sort_by not in valid_sort_fields:
#             raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid sort_by. Must be one of: {valid_sort_fields}")
        
#         # Validate sort_order
#         if sort_order not in ["asc", "desc"]:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid sort_order. Must be 'asc' or 'desc'")
        
#         # Validate price range
#         if price_min is not None and price_max is not None and price_min > price_max:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "price_min cannot be greater than price_max")
        
#         # Validate and normalize type parameter
#         validated_type = None
#         if type is not None:
#             print(f"🔍 Validating type parameter: '{type}'")
#             # Map common variations to proper enum values
#             type_mapping = {
#                 'trial': 'Trial',
#                 'monthly': 'Monthly Club Membership',
#                 'monthly club membership': 'Monthly Club Membership',
#                 'club ownership': 'Club Ownership',
#                 'club': 'Club Ownership',
#                 'premium': 'Premium Membership',
#                 'premium membership': 'Premium Membership',
#                 'basic': 'Basic Membership',
#                 'basic membership': 'Basic Membership',
#                 'vip': 'VIP Membership',
#                 'vip membership': 'VIP Membership'
#             }
            
#             # Try exact match first, then case-insensitive match
#             if type in type_mapping:
#                 validated_type = type_mapping[type]
#                 print(f"✅ Type mapped: '{type}' -> '{validated_type}'")
#             else:
#                 # Check if it's a valid enum value (case-sensitive)
#                 try:
#                     from .models import SubscriptionPlanType
#                     SubscriptionPlanType(type)
#                     validated_type = type
#                     print(f"✅ Type validated as enum: '{type}'")
#                 except ValueError:
#                     # Try case-insensitive match
#                     type_lower = type.lower()
#                     if type_lower in type_mapping:
#                         validated_type = type_mapping[type_lower]
#                         print(f"✅ Type mapped (case-insensitive): '{type}' -> '{validated_type}'")
#                     else:
#                         valid_types = ['Trial', 'Monthly Club Membership', 'Club Ownership', 'Premium Membership', 'Basic Membership', 'VIP Membership']
#                         print(f"❌ Invalid type: '{type}'")
#                         raise HTTPException(HTTP_400_BAD_REQUEST, f"Invalid type '{type}'. Must be one of: {valid_types}")
        
#         print(f"🔍 Final validated type: {validated_type}")
        
#         # Create request object
#         request = SubscriptionPlanListRequest(
#             search=search,
#             type=validated_type,
#             is_active=is_active,
#             price_min=price_min,
#             price_max=price_max,
#             sort_by=sort_by,
#             sort_order=sort_order,
#             page=page,
#             limit=limit
#         )
        
#         print(f"🔍 Created request object: {request}")
        
#         # Get plans list from service
#         result = await admin_subscription_plans_service.get_subscription_plans_list(request, token)
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in get_subscription_plans_list: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in get_subscription_plans_list: {e}")
#         raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to retrieve subscription plans: {str(e)}")

# @router.post("/subscription-plans/export-csv", response_model=SubscriptionPlanCSVExportResponse)
# async def export_subscription_plans_csv(
#     request: SubscriptionPlanCSVExportRequest,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Export subscription plans to CSV format with custom field selection
    
#     **Features:**
#     - **Custom Field Selection**: Choose which fields to include in export
#     - **Filtering**: Apply same filters as list endpoint
#     - **Sorting**: Sort data before export
#     - **Dynamic Filename**: Timestamped filename for easy identification
#     - **CSV Format**: Standard CSV with proper headers
    
#     **Request Body:**
#     ```json
#     {
#         "search": "trial",
#         "type": "Trial",
#         "is_active": true,
#         "price_min": 0,
#         "price_max": 100,
#         "fields": ["name", "type", "price", "active_subscribers"],
#         "sort_by": "name",
#         "sort_order": "asc"
#     }
#     ```
    
#     **Available Fields:**
#     - `name`: Plan name
#     - `type`: Plan type
#     - `price`: Plan price
#     - `active_subscribers`: Number of active subscribers
#     - `is_active`: Active status
#     - `created_at`: Creation date
#     - `updated_at`: Last update date
#     - `description`: Plan description
    
#     **Response includes:**
#     - CSV data as string
#     - Suggested filename with timestamp
#     - Total records exported
#     - Fields included in export
    
#     **Example Usage:**
#     ```
#     # Export all active plans with basic fields
#     POST /admin/subscription-plans/export-csv
#     {
#         "is_active": true,
#         "fields": ["name", "type", "price", "active_subscribers"]
#     }
    
#     # Export specific plan type with all fields
#     POST /admin/subscription-plans/export-csv
#     {
#         "type": "Monthly Club Membership",
#         "fields": ["name", "type", "price", "active_subscribers", "is_active", "created_at", "description"]
#     }
#     ```
    
#     Admin-only access required.
#     """
#     try:
#         # Get CSV export from service
#         result = await admin_subscription_plans_service.export_subscription_plans_csv(request, token)
#         return result
        
#     except Exception as e:
#         print(f"Error in export_subscription_plans_csv: {e}")
#         raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to export subscription plans: {str(e)}")

# @router.put("/subscription-plans/{plan_id}/status", response_model=SubscriptionPlanStatusUpdateResponse)
# async def update_subscription_plan_status(
#     plan_id: str,
#     request: SubscriptionPlanStatusUpdateRequest,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Update subscription plan active status
    
#     **Features:**
#     - **Status Toggle**: Activate or deactivate plans
#     - **Validation**: Check if plan exists before update
#     - **Audit Logging**: Log all status changes for admin tracking
#     - **Immediate Effect**: Status changes take effect immediately
    
#     **Path Parameters:**
#     - `plan_id`: ID of the subscription plan to update
    
#     **Request Body:**
#     ```json
#     {
#         "plan_id": "64f7b1234567890abcdef123",
#         "is_active": false
#     }
#     ```
    
#     **Response includes:**
#     - Success status and message
#     - Plan ID that was updated
#     - Previous and new status
#     - Update timestamp
    
#     **Use Cases:**
#     - Temporarily disable plans during maintenance
#     - Activate new plans for launch
#     - Deactivate deprecated plans
#     - Emergency plan suspension
    
#     **Example Usage:**
#     ```
#     # Deactivate a plan
#     PUT /admin/subscription-plans/64f7b1234567890abcdef123/status
#     {
#         "plan_id": "64f7b1234567890abcdef123",
#         "is_active": false
#     }
    
#     # Reactivate a plan
#     PUT /admin/subscription-plans/64f7b1234567890abcdef123/status
#     {
#         "plan_id": "64f7b1234567890abcdef123",
#         "is_active": true
#     }
#     ```
    
#     Admin-only access required.
#     """
#     try:
#         # Validate plan_id format
#         try:
#             ObjectId(plan_id)
#         except:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid plan_id format")
        
#         # Ensure plan_id in request matches path parameter
#         if request.plan_id != plan_id:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Plan ID in request body must match path parameter")
        
#         # Update plan status via service
#         result = await admin_subscription_plans_service.update_subscription_plan_status(request, token)
#         return result
        
#     except ValueError as ve:
#         print(f"Validation error in update_subscription_plan_status: {ve}")
#         raise HTTPException(HTTP_400_BAD_REQUEST, str(ve))
#     except Exception as e:
#         print(f"Error in update_subscription_plan_status: {e}")
#         raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to update subscription plan status: {str(e)}")

# @router.delete("/subscription-plans/{plan_id}", response_model=SubscriptionPlanDeleteResponse)
# async def delete_subscription_plan(
#     plan_id: str,
#     token: str = Depends(get_current_admin)
# ):
#     """
#     Soft delete subscription plan (mark as deleted)
    
#     **Features:**
#     - **Soft Delete**: Plan is marked as deleted but not physically removed
#     - **Safety Check**: Prevents deletion if plan has active subscriptions
#     - **Audit Logging**: Logs deletion action for admin tracking
#     - **Data Preservation**: All plan data is retained for historical purposes
    
#     **Path Parameters:**
#     - `plan_id`: ID of the subscription plan to delete
    
#     **Safety Checks:**
#     - Plan must exist
#     - Plan must not have active subscriptions
#     - Admin must have proper permissions
    
#     **Response includes:**
#     - Success status and message
#     - Deleted plan ID
#     - Deletion timestamp
    
#     **Use Cases:**
#     - Remove outdated plans
#     - Clean up test plans
#     - Archive discontinued plans
#     - Maintain data integrity
    
#     **Example Usage:**
#     ```
#     # Delete a subscription plan
#     DELETE /admin/subscription-plans/64f7b1234567890abcdef123
#     ```
    
#     **Note:** This is a soft delete operation. The plan will be marked as deleted
#     but all data will be preserved. Plans with active subscriptions cannot be deleted.
    
#     Admin-only access required.
#     """
#     try:
#         # Validate plan_id format
#         try:
#             ObjectId(plan_id)
#         except:
#             raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid plan_id format")
        
#         # Delete plan via service
#         result = await admin_subscription_plans_service.delete_subscription_plan(plan_id, token)
#         return result
        
#     except Exception as e:
#         print(f"Error in delete_subscription_plan: {e}")
#         raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to delete subscription plan: {str(e)}")

# ============================================================================
# INCLUSIONS MANAGEMENT ENDPOINTS
# ============================================================================

@router.post("/add-inclusions")
async def add_inclusion(
    inclusion_data: InclusionCreateRequest,
    token: str = Depends(get_current_admin)
):
    """
    
    **Example Usage:**
    ```
    # Add a new inclusion
    POST /admin/add-inclusions
    {
        "title": "Premium Picks",
        "sub_desc": "Access to exclusive betting picks",
        "logo_url": "https://example.com/icon.png"
    }
    ```
    
    Admin-only access required.
    """
    try:
        result = await admin_inclusions_service.create_inclusion(inclusion_data)
        if result:
            return create_response(
                status_code=201,
                status="success",
                message="Inclusion created successfully",
                data=result.model_dump()
            )
        else:
            return create_response(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Failed to create inclusion",
                data=None
            )
    except ValueError as e:
        # Handle duplicate title error
        return create_response(
            status_code=409,  # Conflict status code for duplicates
            status="error",
            message=str(e),
            data=None
        )
    except Exception as e:
        print(f"Error in add_inclusion: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to create inclusion: {str(e)}",
            data=None
        )

@router.get("/inclusions")
async def get_inclusions(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by title or description"),
    token: str = Depends(get_current_admin)
):
    """
    Get all inclusions with pagination and search
    
    **Features:**
    - **Pagination**: Supports large datasets with page-based navigation
    - **Search**: Find inclusions by title or description
    - **Sorting**: Results sorted by creation date (newest first)
    - **Admin Only**: Restricted to admin users only
    
    **Query Parameters:**
    - `page`: Page number (default: 1)
    - `page_size`: Items per page (default: 20, max: 100)
    - `search`: Optional search term for title or description
    
    **Response includes:**
    - List of inclusions with pagination info
    - Total count and page navigation
    - Search results if search term provided
    
    **Use Cases:**
    - Browse all inclusions
    - Search for specific features
    - Manage inclusion inventory
    - Review club benefits
    
    **Example Usage:**
    ```
    # Get all inclusions
    GET /admin/inclusions?page=1&page_size=20
    
    # Search inclusions
    GET /admin/inclusions?search=premium&page=1&page_size=10
    ```
    
    Admin-only access required.
    """
    try:
        result = await admin_inclusions_service.get_all_inclusions(page, page_size, search)
        return create_response(
            status_code=200,
            status="success",
            message="Inclusions retrieved successfully",
            data=result.model_dump()
        )
    except Exception as e:
        print(f"Error in get_inclusions: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to get inclusions: {str(e)}",
            data=None
        )

@router.get("/inclusions/check-title/{title}")
async def check_inclusion_title(
    title: str,
    token: str = Depends(get_current_admin)
):
    """
    Check if an inclusion title already exists
    
    **Features:**
    - **Title Check**: Verify if title is available
    - **Case Insensitive**: Handles different case variations
    - **Admin Only**: Restricted to admin users only
    
    **Path Parameters:**
    - `title`: Title to check (URL encoded)
    
    **Response includes:**
    - Boolean indicating if title exists
    - Existing inclusion details if found
    
    **Use Cases:**
    - Frontend validation before form submission
    - Check title availability
    - Prevent duplicate submissions
    
    **Example Usage:**
    ```
    # Check if title exists
    GET /admin/inclusions/check-title/Premium%20Picks
    ```
    
    Admin-only access required.
    """
    try:
        # URL decode the title
        import urllib.parse
        decoded_title = urllib.parse.unquote(title)
        
        # Check if title exists
        existing_inclusion = await admin_inclusions_service.get_inclusion_by_title(decoded_title)
        
        if existing_inclusion:
            return create_response(
                status_code=200,
                status="success",
                message="Title already exists",
                data={
                    "title_exists": True,
                    "existing_inclusion": existing_inclusion.model_dump()
                }
            )
        else:
            return create_response(
                status_code=200,
                status="success",
                message="Title is available",
                data={
                    "title_exists": False,
                    "existing_inclusion": None
                }
            )
            
    except Exception as e:
        print(f"Error in check_inclusion_title: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to check title: {str(e)}",
            data=None
        )

@router.get("/inclusions/titles/all")
async def get_all_inclusion_titles(
    token: str = Depends(get_current_admin)
):
    """
    Get all inclusion titles for validation purposes
    
    **Features:**
    - **All Titles**: Retrieve list of all existing titles
    - **Validation**: Useful for frontend validation
    - **Admin Only**: Restricted to admin users only
    
    **Response includes:**
    - List of all inclusion titles
    - Count of total titles
    
    **Use Cases:**
    - Frontend dropdown validation
    - Check title availability
    - Prevent duplicate submissions
    - Title suggestions
    
    **Example Usage:**
    ```
    # Get all titles
    GET /admin/inclusions/titles/all
    ```
    
    Admin-only access required.
    """
    try:
        titles = await admin_inclusions_service.get_all_titles()
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Retrieved {len(titles)} inclusion titles",
            data={
                "titles": titles,
                "count": len(titles)
            }
        )
            
    except Exception as e:
        print(f"Error in get_all_inclusion_titles: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to get titles: {str(e)}",
            data=None
        )

@router.get("/inclusions/{inclusion_id}")
async def get_inclusion_by_id(
    inclusion_id: str,
    token: str = Depends(get_current_admin)
):
    """
    Get a specific inclusion by ID
    
    **Features:**
    - **Get by ID**: Retrieve specific inclusion details
    - **Validation**: Ensures proper ID format
    - **Admin Only**: Restricted to admin users only
    
    **Path Parameters:**
    - `inclusion_id`: ID of the inclusion to retrieve
    
    **Response includes:**
    - Complete inclusion details
    - Creation and update timestamps
    
    **Use Cases:**
    - View inclusion details
    - Edit inclusion information
    - Review inclusion data
    - Validate inclusion content
    
    **Example Usage:**
    ```
    # Get inclusion by ID
    GET /admin/inclusions/64f7b1234567890abcdef123
    ```
    
    Admin-only access required.
    """
    try:
        # Validate inclusion_id format
        try:
            ObjectId(inclusion_id)
        except:
            return create_response(
                status_code=HTTP_400_BAD_REQUEST,
                status="error",
                message="Invalid inclusion_id format",
                data=None
            )
        
        result = await admin_inclusions_service.get_inclusion_by_id(inclusion_id)
        if result:
            return create_response(
                status_code=200,
                status="success",
                message="Inclusion retrieved successfully",
                data=result.dict()
            )
        else:
            return create_response(
                status_code=HTTP_404_NOT_FOUND,
                status="error",
                message="Inclusion not found",
                data=None
            )
    except Exception as e:
        print(f"Error in get_inclusion_by_id: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to get inclusion: {str(e)}",
            data=None
        )

@router.put("/inclusions/{inclusion_id}")
async def update_inclusion(
    inclusion_id: str,
    inclusion_data: InclusionUpdateRequest,
    token: str = Depends(get_current_admin)
):
    """
    Update an existing inclusion
    
    **Features:**
    - **Update Inclusion**: Modify inclusion details
    - **Partial Updates**: Update only specific fields
    - **Validation**: Ensures proper data format
    - **Admin Only**: Restricted to admin users only
    
    **Path Parameters:**
    - `inclusion_id`: ID of the inclusion to update
    
    **Request Body:**
    - `title`: Optional new title (3-100 characters)
    - `sub_desc`: Optional new description (5-200 characters)
    - `logo_url`: Optional new logo URL
    
    **Response includes:**
    - Updated inclusion details
    - Updated timestamp
    
    **Use Cases:**
    - Modify inclusion titles
    - Update descriptions
    - Change logo URLs
    - Correct information
    
    **Example Usage:**
    ```
    # Update inclusion
    PUT /admin/inclusions/64f7b1234567890abcdef123
    {
        "title": "Updated Premium Picks",
        "sub_desc": "Updated description"
    }
    ```
    
    Admin-only access required.
    """
    try:
        # Validate inclusion_id format
        try:
            ObjectId(inclusion_id)
        except:
            return create_response(
                status_code=HTTP_400_BAD_REQUEST,
                status="error",
                message="Invalid inclusion_id format",
                data=None
            )
        
        result = await admin_inclusions_service.update_inclusion(inclusion_id, inclusion_data)
        if result:
            return create_response(
                status_code=200,
                status="success",
                message="Inclusion updated successfully",
                data=result.model_dump()
            )
        else:
            return create_response(
                status_code=HTTP_404_NOT_FOUND,
                status="error",
                message="Inclusion not found or update failed",
                data=None
            )
    except ValueError as e:
        # Handle duplicate title error
        return create_response(
            status_code=409,  # Conflict status code for duplicates
            status="error",
            message=str(e),
            data=None
        )
    except Exception as e:
        print(f"Error in update_inclusion: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to update inclusion: {str(e)}",
            data=None
        )

@router.delete("/inclusions/{inclusion_id}")
async def delete_inclusion(
    inclusion_id: str,
    token: str = Depends(get_current_admin)
):
    """
    Delete an inclusion
    
    **Features:**
    - **Delete Inclusion**: Remove inclusion from system
    - **Validation**: Ensures proper ID format
    - **Admin Only**: Restricted to admin users only
    
    **Path Parameters:**
    - `inclusion_id`: ID of the inclusion to delete
    
    **Response includes:**
    - Success status and message
    - Deleted inclusion ID
    
    **Use Cases:**
    - Remove outdated inclusions
    - Clean up test data
    - Manage inclusion inventory
    - Archive unused features
    
    **Example Usage:**
    ```
    # Delete inclusion
    DELETE /admin/inclusions/64f7b1234567890abcdef123
    ```
    
    Admin-only access required.
    """
    try:
        # Validate inclusion_id format
        try:
            ObjectId(inclusion_id)
        except:
            return create_response(
                status_code=HTTP_400_BAD_REQUEST,
                status="error",
                message="Invalid inclusion_id format",
                data=None
            )
        
        success = await admin_inclusions_service.delete_inclusion(inclusion_id)
        if success:
            return create_response(
                status_code=200,
                status="success",
                message="Inclusion deleted successfully",
                data={"inclusion_id": inclusion_id}
            )
        else:
            return create_response(
                status_code=HTTP_404_NOT_FOUND,
                status="error",
                message="Inclusion not found or deletion failed",
                data=None
            )
    except Exception as e:
        print(f"Error in delete_inclusion: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to delete inclusion: {str(e)}",
            data=None
        )

# ============================================================================
# SPORTS MANAGEMENT ENDPOINTS
# ============================================================================

@router.post("/sports")
async def add_sport(
    sport_data: SportCreateRequest,
    token: str = Depends(get_current_admin)
):
    """
    Add a new sport
    
    **Features:**
    - **Create Sport**: Add new sports to the system
    - **Validation**: Ensures proper data format and required fields
    - **Admin Only**: Restricted to admin users only
    - **Audit Logging**: Tracks creation for admin monitoring
    
    **Request Body:**
    - `name`: Sport name (2-50 characters)
    - `icon`: URL to sport icon
    
    **Response includes:**
    - Created sport details
    - Creation timestamp
    - Unique sport ID
    
    **Use Cases:**
    - Add new sports
    - Manage sport categories
    - Update sport icons
    - Standardize sport data
    
    **Example Usage:**
    ```
    # Add a new sport
    POST /admin/sports
    {
        "name": "Football",
        "icon": "https://example.com/football-icon.png"
    }
    ```
    
    Admin-only access required.
    """
    try:
        result = await admin_sports_service.create_sport(sport_data)
        if result:
            return create_response(
                status_code=201,
                status="success",
                message="Sport created successfully",
                data=result.model_dump()
            )
        else:
            return create_response(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                status="error",
                message="Failed to create sport",
                data=None
            )
    except ValueError as e:
        # Handle duplicate name error
        return create_response(
            status_code=409,  # Conflict status code for duplicates
            status="error",
            message=str(e),
            data=None
        )
    except Exception as e:
        print(f"Error in add_sport: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to create sport: {str(e)}",
            data=None
        )

@router.get("/sports")
async def get_sports(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by sport name"),
    token: str = Depends(get_current_admin)
):
    """
    Get all sports with pagination and search
    
    **Features:**
    - **Pagination**: Supports large datasets with page-based navigation
    - **Search**: Find sports by name
    - **Sorting**: Results sorted alphabetically by name
    - **Admin Only**: Restricted to admin users only
    
    **Query Parameters:**
    - `page`: Page number (default: 1)
    - `page_size`: Items per page (default: 20, max: 100)
    - `search`: Optional search term for sport name
    
    **Response includes:**
    - List of sports with pagination info
    - Total count and page navigation
    - Search results if search term provided
    
    **Use Cases:**
    - Browse all sports
    - Search for specific sports
    - Manage sport inventory
    - Review sport categories
    
    **Example Usage:**
    ```
    # Get all sports
    GET /admin/sports?page=1&page_size=20
    
    # Search sports
    GET /admin/sports?search=football&page=1&page_size=10
    ```
    
    Admin-only access required.
    """
    try:
        result = await admin_sports_service.get_all_sports(page, page_size, search)
        return create_response(
            status_code=200,
            status="success",
            message="Sports retrieved successfully",
            data=result.model_dump()
        )
    except Exception as e:
        print(f"Error in get_sports: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to get sports: {str(e)}",
            data=None
        )

@router.get("/sports/check-name/{name}")
async def check_sport_name(
    name: str,
    token: str = Depends(get_current_admin)
):
    """
    Check if a sport name already exists
    
    **Features:**
    - **Name Check**: Verify if name is available
    - **Case Insensitive**: Handles different case variations
    - **Admin Only**: Restricted to admin users only
    
    **Path Parameters:**
    - `name`: Name to check (URL encoded)
    
    **Response includes:**
    - Boolean indicating if name exists
    - Existing sport details if found
    
    **Use Cases:**
    - Frontend validation before form submission
    - Check name availability
    - Prevent duplicate submissions
    
    **Example Usage:**
    ```
    # Check if name exists
    GET /admin/sports/check-name/Football
    ```
    
    Admin-only access required.
    """
    try:
        # URL decode the name
        import urllib.parse
        decoded_name = urllib.parse.unquote(name)
        
        # Check if name exists
        existing_sport = await admin_sports_service.get_sport_by_name(decoded_name)
        
        if existing_sport:
            return create_response(
                status_code=200,
                status="success",
                message="Name already exists",
                data={
                    "name_exists": True,
                    "existing_sport": existing_sport.model_dump()
                }
            )
        else:
            return create_response(
                status_code=200,
                status="success",
                message="Name is available",
                data={
                    "name_exists": False,
                    "existing_sport": None
                }
            )
            
    except Exception as e:
        print(f"Error in check_sport_name: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to check name: {str(e)}",
            data=None
        )

@router.get("/sports/names/all")
async def get_all_sport_names(
    token: str = Depends(get_current_admin)
):
    """
    Get all sport names for validation purposes
    
    **Features:**
    - **All Names**: Retrieve list of all existing names
    - **Validation**: Useful for frontend validation
    - **Admin Only**: Restricted to admin users only
    
    **Response includes:**
    - List of all sport names
    - Count of total names
    
    **Use Cases:**
    - Frontend dropdown validation
    - Check name availability
    - Prevent duplicate submissions
    - Name suggestions
    
    **Example Usage:**
    ```
    # Get all names
    GET /admin/sports/names/all
    ```
    
    Admin-only access required.
    """
    try:
        names = await admin_sports_service.get_all_names()
        
        return create_response(
            status_code=200,
            status="success",
            message=f"Retrieved {len(names)} sport names",
            data={
                "names": names,
                "count": len(names)
            }
        )
            
    except Exception as e:
        print(f"Error in get_all_sport_names: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to get names: {str(e)}",
            data=None
        )

@router.get("/sports/{sport_id}")
async def get_sport_by_id(
    sport_id: str,
    token: str = Depends(get_current_admin)
):
    """
    Get a specific sport by ID
    
    **Features:**
    - **Get by ID**: Retrieve specific sport details
    - **Validation**: Ensures proper ID format
    - **Admin Only**: Restricted to admin users only
    
    **Path Parameters:**
    - `sport_id`: ID of the sport to retrieve
    
    **Response includes:**
    - Complete sport details
    - Creation and update timestamps
    
    **Use Cases:**
    - View sport details
    - Edit sport information
    - Review sport data
    - Validate sport content
    
    **Example Usage:**
    ```
    # Get sport by ID
    GET /admin/sports/64f7b1234567890abcdef123
    ```
    
    Admin-only access required.
    """
    try:
        # Validate sport_id format
        try:
            ObjectId(sport_id)
        except:
            return create_response(
                status_code=HTTP_400_BAD_REQUEST,
                status="error",
                message="Invalid sport_id format",
                data=None
            )
        
        result = await admin_sports_service.get_sport_by_id(sport_id)
        if result:
            return create_response(
                status_code=200,
                status="success",
                message="Sport retrieved successfully",
                data=result.model_dump()
            )
        else:
            return create_response(
                status_code=HTTP_404_NOT_FOUND,
                status="error",
                message="Sport not found",
                data=None
            )
    except Exception as e:
        print(f"Error in get_sport_by_id: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to get sport: {str(e)}",
            data=None
        )

@router.put("/sports/{sport_id}")
async def update_sport(
    sport_id: str,
    sport_data: SportUpdateRequest,
    token: str = Depends(get_current_admin)
):
    """
    Update an existing sport
    
    **Features:**
    - **Update Sport**: Modify sport details
    - **Partial Updates**: Update only specific fields
    - **Validation**: Ensures proper data format
    - **Admin Only**: Restricted to admin users only
    
    **Path Parameters:**
    - `sport_id`: ID of the sport to update
    
    **Request Body:**
    - `name`: Optional new sport name (2-50 characters)
    - `icon`: Optional new icon URL
    
    **Response includes:**
    - Updated sport details
    - Updated timestamp
    
    **Use Cases:**
    - Modify sport names
    - Update sport icons
    - Correct information
    - Standardize naming
    
    **Example Usage:**
    ```
    # Update sport
    PUT /admin/sports/64f7b1234567890abcdef123
    {
        "name": "American Football",
        "icon": "https://example.com/american-football-icon.png"
    }
    ```
    
    Admin-only access required.
    """
    try:
        # Validate sport_id format
        try:
            ObjectId(sport_id)
        except:
            return create_response(
                status_code=HTTP_400_BAD_REQUEST,
                status="error",
                message="Invalid sport_id format",
                data=None
            )
        
        result = await admin_sports_service.update_sport(sport_id, sport_data)
        if result:
            return create_response(
                status_code=200,
                status="success",
                message="Sport updated successfully",
                data=result.model_dump()
            )
        else:
            return create_response(
                status_code=HTTP_404_NOT_FOUND,
                status="error",
                message="Sport not found or update failed",
                data=None
            )
    except ValueError as e:
        # Handle duplicate name error
        return create_response(
            status_code=409,  # Conflict status code for duplicates
            status="error",
            message=str(e),
            data=None
        )
    except Exception as e:
        print(f"Error in update_sport: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to update sport: {str(e)}",
            data=None
        )

@router.delete("/sports/{sport_id}")
async def delete_sport(
    sport_id: str,
    token: str = Depends(get_current_admin)
):
    """
    Delete a sport
    
    **Features:**
    - **Delete Sport**: Remove sport from system
    - **Validation**: Ensures proper ID format
    - **Admin Only**: Restricted to admin users only
    
    **Path Parameters:**
    - `sport_id`: ID of the sport to delete
    
    **Response includes:**
    - Success status and message
    - Deleted sport ID
    
    **Use Cases:**
    - Remove outdated sports
    - Clean up test data
    - Manage sport inventory
    - Archive unused sports
    
    **Example Usage:**
    ```
    # Delete sport
    DELETE /admin/sports/64f7b1234567890abcdef123
    ```
    
    Admin-only access required.
    """
    try:
        # Validate sport_id format
        try:
            ObjectId(sport_id)
        except:
            return create_response(
                status_code=HTTP_400_BAD_REQUEST,
                status="error",
                message="Invalid sport_id format",
                data=None
            )
        
        success = await admin_sports_service.delete_sport(sport_id)
        if success:
            return create_response(
                status_code=200,
                status="success",
                message="Sport deleted successfully",
                data={"sport_id": sport_id}
            )
        else:
            return create_response(
                status_code=HTTP_404_NOT_FOUND,
                status="error",
                message="Sport not found or deletion failed",
                data=None
            )
    except Exception as e:
        print(f"Error in delete_sport: {e}")
        return create_response(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            status="error",
            message=f"Failed to delete sport: {str(e)}",
            data=None
        )

import logging
from .image_service import image_service
logger = logging.getLogger(__name__)
@router.post("/upload-images")
async def upload_general_image(
    file: UploadFile,
    resize: bool = Form(True, description="Whether to resize the image"),
    max_width: int = Form(800, description="Maximum width for resizing"),
    max_height: int = Form(800, description="Maximum height for resizing"),
    quality: int = Form(85, description="JPEG quality (1-100)")
):
    """
    Upload a general image file without authentication
    
    This endpoint allows frontend applications to upload images without requiring user authentication.
    Perfect for general purpose image uploads where user context is not needed.
    
    File requirements:
    - Max size: 10MB
    - Formats: JPG, JPEG, PNG, GIF, WebP
    - Min dimensions: 100x100 pixels
    - Max dimensions: 4000x4000 pixels
    
    Returns:
    - Image URL for immediate use
    - File metadata and processing information
    """
    try:
        # Validate quality parameter
        if not 1 <= quality <= 100:
            return create_response(
                status_code=400,
                status="error",
                message="Quality must be between 1 and 100",
                data=None
            )
        
        # Validate dimensions
        if max_width < 100 or max_height < 100:
            return create_response(
                status_code=400,
                status="error",
                message="Maximum dimensions must be at least 100x100 pixels",
                data=None
            )
        
        # Process and upload image with general purpose
        result = await image_service.process_image(
            file=file,
            purpose="general",
            resize=resize,
            max_width=max_width,
            max_height=max_height,
            quality=quality
        )
        
        # Add general upload metadata
        result["metadata"]["upload_type"] = "general"
        result["metadata"]["requires_auth"] = False
        
        # Convert datetime objects to ISO format strings for JSON serialization
        def convert_datetime_to_iso(obj):
            """Recursively convert datetime objects to ISO format strings"""
            if isinstance(obj, dict):
                return {key: convert_datetime_to_iso(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [convert_datetime_to_iso(item) for item in obj]
            elif hasattr(obj, 'isoformat'):  # datetime objects
                return obj.isoformat()
            else:
                return obj
        
        # Convert the result data to be JSON serializable
        serializable_result = convert_datetime_to_iso(result)
        
        return create_response(
            status_code=200,
            status="success",
            message="General image uploaded successfully",
            data={
                "image_url": serializable_result["image_url"],
                "image_id": serializable_result["image_id"],
                "filename": serializable_result["filename"],
                "file_size": serializable_result["file_size"],
                "content_type": serializable_result["content_type"],
                "upload_timestamp": serializable_result["upload_timestamp"],
                "metadata": serializable_result["metadata"]
            }
        )
        
    except Exception as e:
        logger.error(f"Error uploading general image: {str(e)}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Failed to upload general image: {str(e)}",
            data=None
        )

# Admin router is already defined above with prefix="/api/admin"

@router.post("/delete-user", response_model=AdminDeletionResponse)
async def delete_user(
    request: AdminDeletionRequest,
    current_admin: dict = Depends(get_current_admin),
    http_request: Request = None
):
    """
    Delete a user (member/captain/moderator) with comprehensive Stripe integration
    
    This endpoint allows admins to delete users with two options:
    - **Permanent Deletion**: User and all associated data is permanently deleted
    - **Temporary Deletion**: User is deactivated and can be reactivated later
    
    **Captain Deletion:**
    - Permanent: All clubs created by captain are deleted, all members removed, no refunds
    - Temporary: All clubs become inactive, all members paused, Stripe subscriptions paused
    
    **Member Deletion:**
    - Permanent: Member removed from all clubs, no refunds
    - Temporary: Member paused in all clubs, Stripe subscriptions paused
    
    **Moderator Deletion:**
    - Permanent: Moderator removed from all clubs
    - Temporary: Moderator set to inactive in all clubs
    
    **Stripe Integration:**
    - Automatically pauses/cancels subscriptions based on deletion type
    - Calculates usage stats from Stripe for temporary deletions
    - Handles both confirmed and unconfirmed payments
    
    **Request Body:**
    - `user_id`: ID of the user to delete
    - `user_role`: Role of the user (member/captain/moderator)
    - `deletion_type`: Type of deletion (permanent/temporary)
    - `reason`: Reason for deletion (required)
    - `admin_notes`: Internal admin notes (optional)
    - `notify_user`: Send email notification (default: true)
    
    **Response includes:**
    - Success status and message
    - Affected clubs and members
    - Stripe actions performed
    - Notification status
    - Complete audit trail
    """
    try:
        # Get admin email from token
        admin_email = current_admin.get("email", "")
        
        # Get client IP address for audit logging
        ip_address = None
        if http_request:
            forwarded_for = http_request.headers.get("x-forwarded-for")
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            else:
                ip_address = getattr(http_request.client, "host", None)
        
        # Validate user ID format
        try:
            ObjectId(request.user_id)
        except:
            return create_response(
                status_code=400,
                status="error",
                message="Invalid user ID format",
                data=None
            )
        
        # Validate that reason is provided
        if not request.reason:
            return create_response(
                status_code=400,
                status="error",
                message="Reason is required for user deletion",
                data=None
            )
        
        # Process deletion
        result = await admin_deletion_service.delete_user(
            request=request,
            admin_email=admin_email,
            ip_address=ip_address
        )
        
        if not result.success:
            return create_response(
                status_code=400,
                status="error",
                message=result.message,
                data=None
            )
        
        # Convert result to serializable format
        result_data = {
            "success": result.success,
            "message": result.message,
            "user_id": result.user_id,
            "user_role": result.user_role.value,
            "deletion_type": result.deletion_type.value,
            "previous_status": result.previous_status,
            "new_status": result.new_status,
            "affected_clubs": result.affected_clubs,
            "affected_members": result.affected_members,
            "stripe_actions": result.stripe_actions,
            "notification_sent": result.notification_sent,
            "admin_email": result.admin_email,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None,
            "deletion_id": result.deletion_id
        }
        
        return create_response(
            status_code=200,
            status="success",
            message=f"User {request.deletion_type.value} deletion completed successfully",
            data=result_data
        )
        
    except ValueError as ve:
        print(f"Validation error in delete_user: {ve}")
        return create_response(
            status_code=400,
            status="error",
            message=str(ve),
            data=None
        )
    except Exception as e:
        print(f"Error in delete_user: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error processing user deletion: {str(e)}",
            data=None
        )

@router.post("/reactivate-user", response_model=AdminReactivationResponse)
async def reactivate_user(
    request: AdminReactivationRequest,
    current_admin: dict = Depends(get_current_admin),
    http_request: Request = None
):
    """
    Reactivate a temporarily deleted user with proper Stripe integration
    
    This endpoint allows admins to reactivate users who were temporarily deleted.
    The system will:
    - Reactivate the user account
    - Resume all club memberships
    - Unpause Stripe subscriptions
    - Apply remaining days to billing cycles
    
    **Captain Reactivation:**
    - All clubs created by captain become active again
    - All members in those clubs are reactivated
    - Stripe subscriptions resume with remaining days applied
    
    **Member Reactivation:**
    - Member is reactivated in all previously joined clubs
    - Stripe subscriptions resume with remaining days applied
    - If reactivated after subscription end, remaining days extend next billing cycle
    
    **Moderator Reactivation:**
    - Moderator is reactivated in all clubs where they had moderator role
    
    **Request Body:**
    - `user_id`: ID of the user to reactivate
    - `user_role`: Role of the user (member/captain/moderator)
    - `reason`: Reason for reactivation (required)
    - `admin_notes`: Internal admin notes (optional)
    - `notify_user`: Send email notification (default: true)
    
    **Response includes:**
    - Success status and message
    - Affected clubs and members
    - Stripe actions performed
    - Notification status
    - Complete audit trail
    """
    try:
        # Get admin email from token
        admin_email = current_admin.get("email", "")
        
        # Get client IP address for audit logging
        ip_address = None
        if http_request:
            forwarded_for = http_request.headers.get("x-forwarded-for")
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            else:
                ip_address = getattr(http_request.client, "host", None)
        
        # Validate user ID format
        try:
            ObjectId(request.user_id)
        except:
            return create_response(
                status_code=400,
                status="error",
                message="Invalid user ID format",
                data=None
            )
        
        # Validate that reason is provided
        if not request.reason:
            return create_response(
                status_code=400,
                status="error",
                message="Reason is required for user reactivation",
                data=None
            )
        
        # Process reactivation
        result = await admin_deletion_service.reactivate_user(
            request=request,
            admin_email=admin_email,
            ip_address=ip_address
        )
        
        if not result.success:
            return create_response(
                status_code=400,
                status="error",
                message=result.message,
                data=None
            )
        
        # Convert result to serializable format
        result_data = {
            "success": result.success,
            "message": result.message,
            "user_id": result.user_id,
            "user_role": result.user_role.value,
            "previous_status": result.previous_status,
            "new_status": result.new_status,
            "affected_clubs": result.affected_clubs,
            "affected_members": result.affected_members,
            "stripe_actions": result.stripe_actions,
            "notification_sent": result.notification_sent,
            "admin_email": result.admin_email,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None,
            "reactivation_id": result.reactivation_id
        }
        
        return create_response(
            status_code=200,
            status="success",
            message="User reactivation completed successfully",
            data=result_data
        )
        
    except ValueError as ve:
        print(f"Validation error in reactivate_user: {ve}")
        return create_response(
            status_code=400,
            status="error",
            message=str(ve),
            data=None
        )
    except Exception as e:
        print(f"Error in reactivate_user: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error processing user reactivation: {str(e)}",
            data=None
        )


# ============================================================================
# ADMIN STATISTICS ENDPOINTS
# ============================================================================

@router.get("/statistics/dashboard", dependencies=[Depends(security_scheme)])
async def get_admin_dashboard_statistics(
    start_date: Optional[str] = Query(None, description="Start date in format YYYY-MM-DD (e.g., 2024-01-01). Defaults to current month first date."),
    end_date: Optional[str] = Query(None, description="End date in format YYYY-MM-DD (e.g., 2024-01-31). Defaults to today's date."),
    month_filter: Optional[str] = Query(None, description="Month filter in format YYYY-MM (e.g., 2024-01) - DEPRECATED, use start_date/end_date instead"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    token: str = Depends(get_current_admin)
):
    """
    Get comprehensive dashboard statistics for admin.
    
    **Admin-only access.**
    
    **Query Parameters:**
    - `start_date`: Optional start date in format "YYYY-MM-DD" (e.g., "2024-01-01"). Defaults to current month first date.
    - `end_date`: Optional end date in format "YYYY-MM-DD" (e.g., "2024-01-31"). Defaults to today's date.
    - `month_filter`: DEPRECATED - use start_date/end_date instead. Month filter in format "YYYY-MM" (e.g., "2024-01")
    - `page`: Page number for pagination (default: 1)
    - `limit`: Items per page (default: 20, max: 100)
    
    **Date Filtering Logic:**
    - If no dates provided: Uses current month first date to today
    - If only start_date provided: Uses start_date to today
    - If only end_date provided: Uses current month first date to end_date
    - If both provided: Uses start_date to end_date
    - All statistics are filtered according to the date range
    
    **Returns:**
    - Total registered users (within date range)
    - Newly registered users in last 24 hours
    - Users registered in selected date range
    - Total approved clubs (within date range)
    - Total pending clubs (within date range)
    - Total clubs (pending + approved + rejected within date range)
    - Total picks (within date range)
    - Club requests received in last 24 hours (with count and club names)
    - User role breakdown (captains, moderators, members within date range)
    - User status breakdown (active/inactive by role within date range)
    - Date range information
    - Pagination information
    
    **Example Response:**
    ```json
    {
      "status": "success",
      "message": "Dashboard statistics retrieved successfully",
      "data": {
        "total_registered_users": 461,
        "newly_registered_last_24h": 5,
        "users_registered_selected_month": 147,
        "total_approved_clubs": 63,
        "total_pending_clubs": 7,
        "total_clubs": 70,
        "total_picks": 21,
        "club_requests_last_24h": {
          "count": 2,
          "club_names": ["ZONE CLUB", "Setup Club"]
        },
        "user_role_breakdown": {
          "total_captains": 261,
          "total_moderators": 100,
          "total_members": 100
        },
        "user_status_breakdown": {
          "total_active_users": 311,
          "total_inactive_users": 150,
          "captains": {
            "active": 200,
            "inactive": 61,
            "total": 261
          },
          "moderators": {
            "active": 60,
            "inactive": 40,
            "total": 100
          },
          "members": {
            "active": 51,
            "inactive": 49,
            "total": 100
          }
        },
        "month_filter": null,
        "pagination": {
          "page": 1,
          "limit": 20,
          "total_pages": 24
        },
        "generated_at": "2025-10-16T05:20:17.795530+00:00"
      }
    }
    ```
    """
    try:
        service = get_admin_statistics_service()
        statistics = await service.get_dashboard_statistics(
            start_date=start_date,
            end_date=end_date,
            month_filter=month_filter,
            page=page,
            limit=limit
        )
        
        return create_response(
            status_code=200,
            status="success",
            message="Dashboard statistics retrieved successfully",
            data=statistics
        )
        
    except Exception as e:
        print(f"Error in get_admin_dashboard_statistics: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error retrieving dashboard statistics: {str(e)}",
            data=None
        )


@router.get("/statistics/users/detailed", dependencies=[Depends(security_scheme)])
async def get_detailed_user_statistics(
    month_filter: Optional[str] = Query(None, description="Month filter in format YYYY-MM (e.g., 2024-01)"),
    token: str = Depends(get_current_admin)
):
    """
    Get detailed user statistics for admin.
    
    **Admin-only access.**
    
    **Query Parameters:**
    - `month_filter`: Optional month filter in format "YYYY-MM" (e.g., "2024-01")
    
    **Returns:**
    - User distribution by role
    - Registration trends (last 7 days, last 30 days)
    - Registrations in selected month
    
    **Example Response:**
    ```json
    {
      "status": "success",
      "message": "Detailed user statistics retrieved successfully",
      "data": {
        "role_distribution": {
          "Member": 1000,
          "Captain": 200,
          "Moderator": 50
        },
        "registrations_last_7_days": 25,
        "registrations_last_30_days": 120,
        "registrations_selected_month": 180,
        "month_filter": "2024-01",
        "generated_at": "2024-01-15T10:30:00Z"
      }
    }
    ```
    """
    try:
        service = get_admin_statistics_service()
        statistics = await service.get_detailed_user_statistics(month_filter=month_filter)
        
        return create_response(
            status_code=200,
            status="success",
            message="Detailed user statistics retrieved successfully",
            data=statistics
        )
        
    except Exception as e:
        print(f"Error in get_detailed_user_statistics: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error retrieving detailed user statistics: {str(e)}",
            data=None
        )


@router.get("/statistics/clubs/detailed", dependencies=[Depends(security_scheme)])
async def get_detailed_club_statistics(
    month_filter: Optional[str] = Query(None, description="Month filter in format YYYY-MM (e.g., 2024-01)"),
    token: str = Depends(get_current_admin)
):
    """
    Get detailed club statistics for admin.
    
    **Admin-only access.**
    
    **Query Parameters:**
    - `month_filter`: Optional month filter in format "YYYY-MM" (e.g., "2024-01")
    
    **Returns:**
    - Club distribution by status
    - Club creation trends (last 7 days, last 30 days)
    - Clubs created in selected month
    
    **Example Response:**
    ```json
    {
      "status": "success",
      "message": "Detailed club statistics retrieved successfully",
      "data": {
        "status_distribution": {
          "approved": 45,
          "pending": 8,
          "rejected": 2
        },
        "clubs_created_last_7_days": 3,
        "clubs_created_last_30_days": 15,
        "clubs_created_selected_month": 12,
        "month_filter": "2024-01",
        "generated_at": "2024-01-15T10:30:00Z"
      }
    }
    ```
    """
    try:
        service = get_admin_statistics_service()
        statistics = await service.get_detailed_club_statistics(month_filter=month_filter)
        
        return create_response(
            status_code=200,
            status="success",
            message="Detailed club statistics retrieved successfully",
            data=statistics
        )
        
    except Exception as e:
        print(f"Error in get_detailed_club_statistics: {e}")
        return create_response(
            status_code=500,
            status="error",
            message=f"Error retrieving detailed club statistics: {str(e)}",
            data=None
        )


