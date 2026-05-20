from fastapi import APIRouter, HTTPException, status, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from ..models import (
    EmailPasswordLoginRequest,
    EmailPasswordLoginResponse,
    LogoutRequest,
    LogoutResponse,
    SessionListResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
)
from ..utils import (
    get_user_by_email,
    verify_password,
    create_access_token,
    create_refresh_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ACCESS_TOKEN_EXPIRE_MINUTES_REMEMBER,
    get_current_user,
    blacklist_token,
    invalidate_user_sessions,
    get_user_active_sessions,
    create_user_session,
    verify_token,
)
from ..db import get_user_collection
from bson import ObjectId
from datetime import datetime, timezone
import os

router = APIRouter()
security = HTTPBearer()


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    logout_data: LogoutRequest = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Enhanced logout with secure session invalidation and inactivity timeout support.

    **Features:**
    - **Secure Token Invalidation**: Blacklists JWT token server-side
    - **Session Management**: Tracks and invalidates active sessions
    - **All Devices Logout**: Option to logout from all devices
    - **Audit Trail**: Logs all logout activities with timestamp and reason
    - **Device Tracking**: Supports device-specific logout tracking

    **Request Body (Optional):**
    ```json
    {
      "all_devices": false,
      "device_id": "device_12345",
      "reason": "manual_logout"
    }
    ```

    **Success Response:**
    ```json
    {
      "message": "Logout successful",
      "success": true,
      "sessions_invalidated": 1,
      "all_devices": false,
      "timestamp": "2025-01-25T14:30:00Z"
    }
    ```

    **Security Features:**
    - Token immediately blacklisted (401 on future requests)
    - Session invalidated in database
    - Activity logged for audit purposes
    - Supports both single device and all devices logout

    **Inactivity Timeout:**
    - Sessions automatically expire after 30 minutes of inactivity
    - Users get 401 Unauthorized on next request after timeout
    - Timeout information included in error response

    **Use Cases:**
    - **Manual Logout**: User clicks logout button
    - **Security Logout**: User wants to logout from all devices
    - **Device Management**: User manages specific device sessions
    """
    try:
        # Initialize logout data if not provided
        if logout_data is None:
            logout_data = LogoutRequest()

        # Get current user information from token
        current_user = await get_current_user(credentials)
        user_id = current_user["user_id"]

        print(
            f"🚪 Logout request for user {user_id} - All devices: {logout_data.all_devices}"
        )

        # Get token from credentials
        token = credentials.credentials

        # Blacklist the current token
        blacklist_success = await blacklist_token(
            token, user_id, reason=logout_data.reason or "manual_logout"
        )

        if not blacklist_success:
            print(f"⚠️ Failed to blacklist token for user {user_id}")

        # Invalidate sessions
        sessions_invalidated = 0
        if logout_data.all_devices:
            # Invalidate all user sessions
            sessions_invalidated = await invalidate_user_sessions(
                user_id, all_devices=True
            )
        else:
            # Invalidate current session only
            # We need to find session by token hash since we don't have session_id
            sessions_invalidated = await invalidate_user_sessions(
                user_id, all_devices=False
            )
            # If single session invalidation failed, try to invalidate by token blacklisting
            if sessions_invalidated == 0:
                sessions_invalidated = 1 if blacklist_success else 0

        # Invalidate refresh token if logging out from all devices
        if logout_data.all_devices:
            from ..db import get_user_collection
            from bson import ObjectId

            users_collection = get_user_collection()

            await users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$unset": {"refresh_token": "", "refresh_token_created_at": ""},
                    "$set": {"updated_at": datetime.utcnow()},
                },
            )
            print(f"✅ Refresh token invalidated for user: {user_id}")

        # # Deactivate FCM device token(s)
        # try:
        #     from services.notifications.notification_service import remove_device_token
        #     from core.database.collections import get_collections
        #     from datetime import timezone

        #     print(logout_data.all_devices,"logout_data.all_devices")
        #     if logout_data.all_devices:
        #         c = get_collections()
        #         col = c.get_user_tokens_collection()
        #         now = datetime.now(timezone.utc)
        #         result = await col.update_many(
        #             {"user_id": user_id, "is_active": True},
        #             {"$set": {"is_active": False, "updated_at": now}},
        #         )
        #         print(
        #             f"✅ Deactivated {result.modified_count} FCM tokens for user {user_id} (all devices)"
        #         )
        #     else:
        #         c = get_collections()
        #         col = c.get_user_tokens_collection()
        #         now = datetime.now(timezone.utc)
        #         tokens_updated = 0

        #         if logout_data.device_id:
        #             result = await col.update_one(
        #                 {"user_id": user_id, "device_id": logout_data.device_id},
        #                 {"$set": {"is_active": False, "updated_at": now}},
        #             )
        #             tokens_updated = result.modified_count
        #             print(
        #                 f"✅ Deactivated token by device_id for user {user_id}: {logout_data.device_id} (updated {result.modified_count})"
        #             )

        #         if tokens_updated == 0 and logout_data.device_token:
        #             token_result = await remove_device_token(
        #                 user_id, logout_data.device_token
        #             )
        #             print(token_result, "token_result")
        #             if token_result.get("success"):
        #                 tokens_updated = 1
        #                 print(
        #                     f"✅ FCM token deactivated for user {user_id}: {logout_data.device_token[:20]}..."
        #                 )
        #             else:
        #                 print(
        #                     f"⚠️ Failed to deactivate FCM token: {token_result.get('error')}"
        #                 )

        #         if (
        #             tokens_updated == 0
        #             and logout_data.device_id
        #             and not logout_data.device_token
        #         ):
        #             # Attempt fallback by removing any token with missing device_id match
        #             result = await col.update_one(
        #                 {"user_id": user_id, "device_id": None},
        #                 {"$set": {"is_active": False, "updated_at": now}},
        #             )
        #             if result.modified_count:
        #                 print(
        #                     f"✅ Fallback deactivation for user {user_id} without device_id (updated {result.modified_count})"
        #                 )
        #             else:
        #                 print(
        #                     f"⚠️ No matching FCM token found to deactivate for device {logout_data.device_id}"
        #                 )
        # except Exception as token_error:
        #     print(f"⚠️ Error deactivating FCM token: {str(token_error)}")
        #     # Don't fail logout if token deletion fails

        # try:
        #     from services.notifications.notification_service import remove_device_token
        #     from core.database.collections import get_collections
        #     from datetime import timezone

        #     c = get_collections()
        #     col = c.get_user_tokens_collection()

        #     if logout_data.all_devices:
        #         # DELETE all tokens for this user
        #         result = await col.delete_many({"user_id": user_id})
        #         print(f"🗑️ Deleted {result.deleted_count} FCM tokens for user {user_id} (all devices)")
        #     else:
        #         tokens_deleted = 0

        #         # Delete by device_id
        #         if logout_data.device_id:
        #             result = await col.delete_one(
        #                 {"user_id": user_id, "device_id": logout_data.device_id}
        #             )
        #             tokens_deleted = result.deleted_count
        #             print(
        #                 f"🗑️ Deleted FCM token for user {user_id}, device_id: {logout_data.device_id} "
        #                 f"(deleted {result.deleted_count})"
        #             )

        #         # Delete by device_token (if provided)
        #         if tokens_deleted == 0 and logout_data.device_token:
        #             token_result = await remove_device_token(user_id, logout_data.device_token)
        #             print(token_result, "token_result")

        #             if token_result.get("success"):
        #                 tokens_deleted = 1
        #                 print(
        #                     f"🗑️ Deleted FCM token for user {user_id}: {logout_data.device_token[:20]}..."
        #                 )

        #         # Fallback delete: remove token with missing device_id match
        #         if tokens_deleted == 0 and logout_data.device_id and not logout_data.device_token:
        #             result = await col.delete_one(
        #                 {"user_id": user_id, "device_id": None}
        #             )
        #             if result.deleted_count:
        #                 print(
        #                     f"🗑️ Fallback delete for user {user_id} with no device_id match "
        #                     f"(deleted {result.deleted_count})"
        #                 )
        #             else:
        #                 print(
        #                     f"⚠️ No FCM token found to delete for device {logout_data.device_id}"
        #                 )

        # except Exception as token_error:
        #     print(f"⚠️ Error deleting FCM token: {str(token_error)}")

        # DELETE user_tokens entries on logout (works 100%)
        try:
            from core.database.collections import get_collections
            c = get_collections()
            col = c.get_user_tokens_collection()

            print("🔍 Checking user_tokens for deletion for user:", user_id)

            if logout_data.all_devices:
                # Delete ALL tokens belonging to this user
                result = await col.delete_many({"user_id": user_id})
                print(f"🗑️ Deleted {result.deleted_count} tokens for ALL devices")
            else:
                deleted_count = 0

                # Delete by device_id
                if logout_data.device_id:
                    result = await col.delete_one(
                        {"user_id": user_id, "device_id": logout_data.device_id}
                    )
                    deleted_count += result.deleted_count
                    print(f"🗑️ Deleted by device_id={logout_data.device_id}: {result.deleted_count}")

                # Delete by device_token
                if deleted_count == 0 and logout_data.device_token:
                    result = await col.delete_one(
                        {"user_id": user_id, "device_token": logout_data.device_token}
                    )
                    deleted_count += result.deleted_count
                    print(f"🗑️ Deleted by device_token: {result.deleted_count}")

                # Last fallback — delete ANY token for this user if nothing matched
                if deleted_count == 0:
                    result = await col.delete_one({"user_id": user_id})
                    print(f"🗑️ Fallback delete: {result.deleted_count}")

        except Exception as token_error:
            print(f"⚠️ ERROR deleting from user_tokens: {str(token_error)}")


        # Prepare success response
        response_data = LogoutResponse(
            message="Logout successful - session invalidated",
            success=True,
            sessions_invalidated=sessions_invalidated,
            all_devices=logout_data.all_devices,
            timestamp=datetime.utcnow().isoformat(),
        )

        print(
            f"✅ Logout successful for user {user_id} - Sessions invalidated: {sessions_invalidated}"
        )

        return response_data

    except HTTPException as he:
        # Re-raise HTTP exceptions (like token validation errors)
        raise he
    except Exception as e:
        print(f"❌ Logout error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Logout failed due to internal error",
                "success": False,
                "sessions_invalidated": 0,
                "all_devices": False,
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
            },
        )


@router.get("/sessions", response_model=SessionListResponse)
async def get_active_sessions(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Get list of active sessions for the current user.

    **Features:**
    - **Session Overview**: Shows all active sessions with details
    - **Device Information**: Displays device info for each session
    - **Activity Tracking**: Shows last activity time for each session
    - **Expiry Information**: Time until session expires
    - **Current Session**: Identifies which session is making the request

    **Success Response:**
    ```json
    {
      "user_id": "64f7b1234567890abcdef123",
      "total_sessions": 3,
      "current_session_id": "sess_abc123_1640995200",
      "sessions": [
        {
          "session_id": "sess_abc123_1640995200",
          "is_active": true,
          "user_id": "64f7b1234567890abcdef123",
          "last_activity": "2025-01-25T14:30:00",
          "expires_at": "2025-01-26T14:30:00",
          "device_info": "Chrome on Windows",
          "time_until_expiry_minutes": 1440
        }
      ],
      "message": "Retrieved 3 active sessions"
    }
    ```

    **Use Cases:**
    - **Session Management**: User views all active sessions
    - **Security Review**: User checks for unauthorized sessions
    - **Device Management**: User identifies devices to logout from
    """
    try:
        # Get current user information
        current_user = await get_current_user(credentials)
        user_id = current_user["user_id"]

        # Get active sessions for user
        active_sessions = await get_user_active_sessions(user_id)

        # Try to identify current session (by token if possible)
        current_session_id = "unknown"
        token = credentials.credentials
        payload = verify_token(token)
        if payload and payload.get("session_id"):
            current_session_id = payload.get("session_id")

        response_data = SessionListResponse(
            user_id=user_id,
            total_sessions=len(active_sessions),
            current_session_id=current_session_id,
            sessions=active_sessions,
            message=f"Retrieved {len(active_sessions)} active sessions",
        )

        print(f"📊 Sessions list for user {user_id}: {len(active_sessions)} active")
        return response_data

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"❌ Error getting sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve sessions: {str(e)}",
        )


@router.post("/login", response_model=EmailPasswordLoginResponse)
async def email_password_login(request: EmailPasswordLoginRequest, req: Request = None):
    """
    Login user with email and password with enhanced session management
    """
    try:
        print(f"🔐 Email login attempt for: {request.email}")

        # Get user by email
        user = await get_user_by_email(request.email)
        if not user:
            print(f"❌ User not found with email: {request.email}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "message": "Invalid email or password",
                    "access_token": "",
                    "error": "invalid_credentials",
                },
            )

        print(f"✅ User found: {user.get('full_name', 'Unknown')}")

        # Verify password
        if not verify_password(request.password, user.get("password_hash", "")):
            print(f"❌ Invalid password for user: {request.email}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "message": "Invalid email or password",
                    "access_token": "",
                    "error": "invalid_credentials",
                },
            )

        print(f"✅ Password verified successfully")

        # Check if user is deleted or temporarily deactivated
        user_status = user.get("status", "active")
        membership_status = user.get("membership_status", "active")
        is_permanent_deactivate = user.get("is_permanent_deactivate", False)
        is_deleted_temp_admin = user.get("is_deleted_temp_admin", False)
        is_deleted_per_admin = user.get("is_deleted_per_admin", False)

        # Simple OR: block login if ANY of these flags is true
        if is_permanent_deactivate or is_deleted_temp_admin or is_deleted_per_admin:
            if is_permanent_deactivate:
                print(
                    f"❌ Login blocked - User {request.email} is temporarily deactivated"
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "message": "Access denied. Your account is temporarily deactivated. Please reactivate your account to continue.",
                        "access_token": "",
                        "error": "account_temporarily_deactivated",
                        "is_permanent_deactivate": True,
                    },
                )
            if is_deleted_temp_admin:
                print(
                    f"❌ Login blocked - User {request.email} has been temporarily deleted by admin"
                )
                deactivated_at = user.get("deactivated_at")
                if deactivated_at and hasattr(deactivated_at, "isoformat"):
                    deactivated_at = deactivated_at.isoformat()
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "message": "Access denied. Your account has been temporarily suspended by admin. Please contact support.",
                        "access_token": "",
                        "error": "account_temporarily_deleted_admin",
                        "is_deleted_temp_admin": True,
                        "deactivated_at": deactivated_at,
                        "deactivated_by": user.get("deactivated_by"),
                        "deactivation_reason": user.get("deactivation_reason"),
                    },
                )
            # is_deleted_per_admin
            print(
                f"❌ Login blocked - User {request.email} has been permanently deleted by admin"
            )
            deactivated_at = user.get("deactivated_at")
            if deactivated_at and hasattr(deactivated_at, "isoformat"):
                deactivated_at = deactivated_at.isoformat()
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "message": "Access denied. Your account has been permanently suspended by admin. Please contact support.",
                    "access_token": "",
                    "error": "account_deleted_admin",
                    "is_deleted_per_admin": True,
                    "deactivated_at": deactivated_at,
                    "deactivated_by": user.get("deactivated_by"),
                    "deactivation_reason": user.get("deactivation_reason"),
                },
            )

        # Block login for deleted users
        if user_status == "deleted" or membership_status == "deleted":
            print(
                f"❌ Login blocked - User {request.email} has been permanently deleted"
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "message": "Access denied. Your account has been permanently deleted.",
                    "access_token": "",
                    "error": "account_deleted",
                    "user_status": user_status,
                    "membership_status": membership_status,
                },
            )

        # Block login for temporarily deactivated users
        if is_permanent_deactivate:
            print(f"❌ Login blocked - User {request.email} is temporarily deactivated")
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "message": "Access denied. Your account is temporarily deactivated. Please reactivate your account to continue.",
                    "access_token": "",
                    "error": "account_temporarily_deactivated",
                    "is_permanent_deactivate": is_permanent_deactivate,
                },
            )

        # Block login for users temporarily deleted by admin
        if is_deleted_temp_admin:
            print(
                f"❌ Login blocked - User {request.email} has been temporarily deleted by admin"
            )

            # Convert datetime to ISO format string if it exists
            deactivated_at = user.get("deactivated_at")
            if deactivated_at and hasattr(deactivated_at, "isoformat"):
                deactivated_at = deactivated_at.isoformat()

            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "message": "Access denied. Your account has been temporarily suspended by admin. Please contact support.",
                    "access_token": "",
                    "error": "account_temporarily_deleted_admin",
                    "is_deleted_temp_admin": is_deleted_temp_admin,
                    "deactivated_at": deactivated_at,
                    "deactivated_by": user.get("deactivated_by"),
                    "deactivation_reason": user.get("deactivation_reason"),
                },
            )

        # Validate membership status - only allow login for active trial or paid memberships
        membership_type = user.get("membership_type", "none")

        # if membership_status != "active":
        #     print(f"❌ Login blocked - User {request.email} has inactive membership status: {membership_status}")
        #     return JSONResponse(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         content={
        #             "message": "Access denied. Your membership is not active. Please complete your subscription to continue.",
        #             "access_token": "",
        #             "error": "membership_inactive",
        #             "membership_status": membership_status,
        #             "membership_type": membership_type
        #         }
        #     )

        # if membership_type not in ["trial", "paid"]:
        #     print(f"❌ Login blocked - User {request.email} has invalid membership type: {membership_type}")
        #     return JSONResponse(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         content={
        #             "message": "Access denied. Invalid membership type. Please contact support.",
        #             "access_token": "",
        #             "error": "invalid_membership_type",
        #             "membership_status": membership_status,
        #             "membership_type": membership_type
        #         }
        #     )

        # print(f"✅ Membership validation passed - Status: {membership_status}, Type: {membership_type}")

        # Initialize Stripe Connect variables
        stripe_connect_account_id = None
        stripe_onboarding_url = None
        stripe_connect_status = None
        stripe_onboarding_incomplete = False
        charges_enabled = None
        payouts_enabled = None
        
        # For Captain role, validate Stripe Connect account status - BLOCK login if incomplete
        if user["role"] == "Captain":
            try:
                # Import Stripe and Connect service
                import stripe
                from services.club.stripe_connect_service import StripeConnectService
                
                stripe_connect_service = StripeConnectService()
                stripe_connect_account_id = user.get("stripe_connect_account_id")
                
                if stripe_connect_account_id:
                    print(f"🔍 Validating Stripe Connect account for Captain: {stripe_connect_account_id}")
                    
                    # Retrieve account from Stripe
                    account = stripe.Account.retrieve(stripe_connect_account_id)
                    
                    charges_enabled = account.charges_enabled
                    payouts_enabled = account.payouts_enabled
                    details_submitted = account.details_submitted
                    
                    # Check if account can process and receive funds
                    if charges_enabled and payouts_enabled:
                        stripe_connect_status = "active"
                        print(f"✅ Stripe Connect account is fully active - Login allowed")
                    else:
                        # Account not ready - BLOCK LOGIN
                        print(f"❌ Login blocked - Stripe Connect account not ready")
                        print(f"   Account ID: {stripe_connect_account_id}")
                        print(f"   charges_enabled: {charges_enabled}, payouts_enabled: {payouts_enabled}, details_submitted: {details_submitted}")
                        
                        # ALWAYS create remediation link - DIRECT APPROACH
                        stripe_onboarding_url = None
                        
                        try:
                            print(f"🔗 Creating Stripe AccountLink for account: {stripe_connect_account_id}")
                            
                            # Determine link type based on details_submitted
                            link_type = 'account_onboarding' if not details_submitted else 'account_update'
                            print(f"   Link type: {link_type}")
                            
                            # Create AccountLink directly using Stripe API
                            account_link = stripe.AccountLink.create(
                                account=stripe_connect_account_id,
                                refresh_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                                return_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                                type=link_type,
                            )
                            
                            stripe_onboarding_url = account_link.url
                            print(f"✅ Successfully created remediation URL: {stripe_onboarding_url}")
                            print(f"   URL expires at: {account_link.expires_at}")
                            
                        except stripe.error.InvalidRequestError as invalid_error:
                            print(f"❌ Invalid request error creating AccountLink: {str(invalid_error)}")
                            # Try alternative link type
                            try:
                                alternative_type = 'account_onboarding' if link_type == 'account_update' else 'account_update'
                                print(f"🔄 Retrying with alternative link type: {alternative_type}")
                                
                                account_link = stripe.AccountLink.create(
                                    account=stripe_connect_account_id,
                                    refresh_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                                    return_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                                    type=alternative_type,
                                )
                                stripe_onboarding_url = account_link.url
                                print(f"✅ Created remediation URL with alternative type: {stripe_onboarding_url}")
                            except Exception as retry_error:
                                print(f"❌ Retry also failed: {str(retry_error)}")
                                
                        except stripe.error.StripeError as stripe_err:
                            print(f"❌ Stripe error creating AccountLink: {str(stripe_err)}")
                            
                        except Exception as general_error:
                            print(f"❌ Unexpected error creating AccountLink: {str(general_error)}")
                        
                        # If still no URL, provide a fallback message
                        if not stripe_onboarding_url:
                            print(f"⚠️ WARNING: Could not generate remediation URL")
                            # Create a support message as fallback
                            error_message = f"Unable to generate verification link. Please contact support with your account ID: {stripe_connect_account_id}"
                        else:
                            # Determine specific status and message
                            if not details_submitted:
                                stripe_connect_status = "pending_onboarding"
                                error_message = "Your Stripe Connect account onboarding is incomplete. Please complete the verification process to access your Captain account."
                            else:
                                stripe_connect_status = "restricted"
                                error_message = "Your Stripe Connect account requires additional verification. Please complete the required steps to access your Captain account."
                        
                        print(f"📤 Returning error response with URL: {stripe_onboarding_url}")
                        
                        # Return error response with remediation link
                        return JSONResponse(
                            status_code=status.HTTP_403_FORBIDDEN,
                            content={
                                "message": error_message,
                                "access_token": "",
                                "error": "stripe_verification_required",
                                "stripe_connect_account_id": stripe_connect_account_id,
                                "stripe_onboarding_url": stripe_onboarding_url,
                                "stripe_connect_status": stripe_connect_status,
                                "charges_enabled": charges_enabled,
                                "payouts_enabled": payouts_enabled,
                                "details_submitted": details_submitted,
                                "remediation_required": True,
                                "remediation_message": "Please click the link below to complete your Stripe Connect verification and enable login." if stripe_onboarding_url else f"Please contact support with account ID: {stripe_connect_account_id}"
                            }
                        )
                else:
                    # Captain has no Stripe Connect account - BLOCK LOGIN
                    print(f"❌ Login blocked - Captain has no Stripe Connect account")
                    
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={
                            "message": "Your Captain account requires Stripe Connect setup. Please contact support to set up your payment account.",
                            "access_token": "",
                            "error": "stripe_account_not_found",
                            "stripe_connect_status": "not_created",
                            "remediation_required": True,
                            "remediation_message": "Please contact support to create your Stripe Connect account."
                        }
                    )
                    
            except stripe.error.StripeError as stripe_error:
                print(f"❌ Stripe error during login validation - Login blocked: {str(stripe_error)}")
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "message": "Unable to verify Stripe Connect account. Please try again later.",
                        "access_token": "",
                        "error": "stripe_service_unavailable",
                        "stripe_error": str(stripe_error)
                    }
                )
            except Exception as e:
                print(f"❌ Error checking Stripe Connect status - Login blocked: {str(e)}")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "message": "An error occurred while verifying your account. Please try again later.",
                        "access_token": "",
                        "error": "verification_error",
                        "details": str(e)
                    }
                )

        # Create access token
        token_data = {
            "sub": str(user["_id"]),
            "phone": user["phone"],
            "email": user["email"],
            "role": user["role"],
            "membership_status": user.get("membership_status", "inactive"),
            "subscription_id": user.get("subscription_id", None),
            "stripe_customer_id": user.get("stripe_customer_id", None),
            "full_name": user.get("full_name", ""),
        }

        # Get club count for both captains and members
        club_count = 0
        if user["role"] == "Captain":
            try:
                from ..utils import get_club_count_for_captain, update_user_club_count

                club_count = await get_club_count_for_captain(str(user["_id"]))
                # Update the user's club count in the database
                await update_user_club_count(str(user["_id"]), club_count)
                print(f"👑 Captain {user['full_name']} has {club_count} clubs")
            except Exception as e:
                print(f"⚠️ Could not get club count for captain: {e}")
                # Use stored club count if available
                club_count = user.get("club_count", 0)
        elif user["role"] == "Member":
            try:
                from ..utils import get_club_count_for_member, update_user_club_count

                club_count = await get_club_count_for_member(str(user["_id"]))
                # Update the user's club count in the database
                await update_user_club_count(str(user["_id"]), club_count)
                print(f"👤 Member {user['full_name']} has {club_count} clubs")
            except Exception as e:
                print(f"⚠️ Could not get club count for member: {e}")
                # Use stored club count if available
                club_count = user.get("club_count", 0)

        access_token = create_access_token(
            data=token_data, remember_me=request.remember_me, club_count=club_count
        )

        # Create refresh token if remember me is enabled
        refresh_token = None
        expires_in = ACCESS_TOKEN_EXPIRE_MINUTES
        if request.remember_me:
            refresh_token = create_refresh_token(token_data)
            expires_in = ACCESS_TOKEN_EXPIRE_MINUTES_REMEMBER
            print(
                f"🔐 Remember me enabled - Refresh token created, expires in {expires_in} minutes"
            )
        else:
            print(f"🔐 Remember me disabled - Token expires in {expires_in} minutes")

        # Prepare user data (exclude sensitive information)
        user_data = {
            "id": str(user["_id"]),
            "full_name": user["full_name"],
            "email": user["email"],
            "phone": user["phone"],
            "role": user["role"],
            "created_at": (
                user["created_at"].isoformat() if user.get("created_at") else None
            ),
            "membership_status": user.get("membership_status", "inactive"),
            # "subscription_id": user.get("subscription_id", None),
            # "stripe_customer_id": user.get("stripe_customer_id", None)
        }

        # Update both access_token and refresh_token in database
        # If tokens already exist, they will be updated with new ones
        try:
            users_collection = get_user_collection()

            update_data = {
                "access_token": access_token,
                "token_created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }

            # Add refresh token if it exists
            if refresh_token:
                update_data["refresh_token"] = refresh_token
                update_data["refresh_token_created_at"] = datetime.utcnow()

            # Always update tokens - this will overwrite existing ones if they exist
            await users_collection.update_one(
                {"_id": ObjectId(str(user["_id"]))}, {"$set": update_data}
            )
            print(
                f"✅ Tokens updated in database for user: {user['_id']} (existing tokens replaced with new ones)"
            )
        except Exception as token_save_error:
            print(f"⚠️ Failed to update tokens in database: {str(token_save_error)}")
            # Don't fail the login if token updating fails

        # Create session for user
        device_info = None
        if req and req.headers:
            user_agent = req.headers.get("user-agent", "Unknown Device")
            device_info = user_agent[:100]  # Limit length

        session_id = await create_user_session(
            str(user["_id"]), access_token, device_info
        )

        # Register/Update FCM device token if provided
        if request.fcm_token:
            from services.notifications.notification_service import register_device_token
            from core.database.collections import get_collections

            # Set default device type if not provided
            device_type = request.device_type or "unknown"
            device_name = request.device_name or "Unknown Device"
            device_id = request.device_id or None
            user_id_str = str(user["_id"])

            try:
                token_result = await register_device_token(
                    user_id=user_id_str,
                    device_token=request.fcm_token,
                    device_type=device_type,
                    device_name=device_name,
                    device_id=device_id,
                )

                if token_result.get("success"):
                    is_new = token_result.get("is_new", True)
                    action = "registered" if is_new else "updated"
                    print(
                        f"✅ FCM token {action} for user {user_id_str}: {token_result.get('message')}"
                    )
                else:
                    print(
                        f"⚠️ Failed to register FCM token via helper: {token_result.get('error')}"
                    )
                    # Fallback: create or update token directly
                    try:
                        collections = get_collections()
                        tokens_col = collections.get_user_tokens_collection()
                        now = datetime.now(timezone.utc)

                        existing = None
                        if device_id:
                            existing = await tokens_col.find_one(
                                {"user_id": user_id_str, "device_id": device_id}
                            )
                        if not existing:
                            existing = await tokens_col.find_one(
                                {"user_id": user_id_str, "device_token": request.fcm_token}
                            )

                        payload = {
                            "device_token": request.fcm_token,
                            "device_type": device_type,
                            "device_name": device_name,
                            "device_id": device_id,
                            "is_active": True,
                            "updated_at": now,
                        }

                        if existing:
                            await tokens_col.update_one(
                                {"_id": existing["_id"]},
                                {"$set": payload},
                            )
                            print(
                                f"✅ Updated existing FCM token directly for user {user_id_str}"
                            )
                        else:
                            doc = {
                                "user_id": user_id_str,
                                "created_at": now,
                                **payload,
                            }
                            await tokens_col.insert_one(doc)
                            print(
                                f"✅ Created FCM token directly for user {user_id_str} (fallback)"
                            )
                    except Exception as fallback_error:
                        print(f"⚠️ Error handling FCM token fallback: {str(fallback_error)}")
            except Exception as token_error:
                print(f"⚠️ Error registering FCM token: {str(token_error)}")
                # Don't fail login if token registration fails

        # Add Stripe Connect info to user data if Captain (only if fully verified)
        if user["role"] == "Captain" and stripe_connect_account_id:
            user_data["stripe_connect_account_id"] = stripe_connect_account_id
            user_data["stripe_connect_status"] = "active"  # Will only reach here if active
            user_data["charges_enabled"] = True
            user_data["payouts_enabled"] = True

        response_data = {
            "message": "Login successful",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": user_data,
            # Stripe Connect fields (only present for verified Captains)
            "stripe_connect_account_id": stripe_connect_account_id if user["role"] == "Captain" else None,
            "stripe_connect_status": stripe_connect_status if user["role"] == "Captain" else None,
            "charges_enabled": charges_enabled if user["role"] == "Captain" else None,
            "payouts_enabled": payouts_enabled if user["role"] == "Captain" else None,
        }

        print(f"✅ Email login successful - Session created: {session_id}")
        if user["role"] == "Captain":
            print(f"✅ Captain Stripe Connect account verified and active")
        return response_data

    except Exception as e:
        print(f"❌ Email login error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Internal server error",
                "access_token": "",
                "error": str(e),
            },
        )


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_access_token(request: RefreshTokenRequest):
    """
    Refresh access token using refresh token when access token expires.

    **Features:**
    - **Token Refresh**: Generates new access token from valid refresh token
    - **Automatic Renewal**: Users stay logged in without re-entering credentials
    - **Security Validation**: Verifies refresh token validity and user status
    - **Membership Check**: Ensures user still has active membership

    **Request Body:**
    ```json
    {
      "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    }
    ```

    **Success Response:**
    ```json
    {
      "message": "Token refreshed successfully",
      "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
      "token_type": "bearer",
      "expires_in": 30,
      "user": {
        "id": "64f7b1234567890abcdef123",
        "full_name": "John Doe",
        "email": "john@example.com",
        "role": "Member",
        "membership_status": "active"
      }
    }
    ```

    **Use Cases:**
    - **Seamless Browsing**: User continues browsing after token expiry
    - **Background Refresh**: Frontend automatically refreshes expired tokens
    - **Session Continuity**: Maintains user session without re-authentication
    """
    try:
        print(f"🔄 Token refresh request received")

        # Verify refresh token
        token_payload = verify_token(request.refresh_token)
        if not token_payload:
            print(f"❌ Invalid or expired refresh token")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "message": "Invalid or expired refresh token",
                    "access_token": "",
                    "error": "invalid_refresh_token",
                },
            )

        user_id = token_payload.get("sub")
        if not user_id:
            print(f"❌ Refresh token missing user ID")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "message": "Invalid refresh token format",
                    "access_token": "",
                    "error": "invalid_token_format",
                },
            )

        print(f"✅ Refresh token validated for user: {user_id}")

        # Get current user data from database
        user = await get_user_by_email(token_payload.get("email", ""))
        if not user:
            print(f"❌ User not found for refresh token: {user_id}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "message": "User not found",
                    "access_token": "",
                    "error": "user_not_found",
                },
            )

        # Validate membership status - ensure user still has active membership
        membership_status = user.get("membership_status", "inactive")
        membership_type = user.get("membership_type", "none")

        if membership_status != "active":
            print(
                f"❌ Token refresh blocked - User {user_id} has inactive membership: {membership_status}"
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "message": "Access denied. Your membership is not active. Please complete your subscription to continue.",
                    "access_token": "",
                    "error": "membership_inactive",
                    "membership_status": membership_status,
                    "membership_type": membership_type,
                },
            )

        if membership_type not in ["trial", "paid"]:
            print(
                f"❌ Token refresh blocked - User {user_id} has invalid membership type: {membership_type}"
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "message": "Access denied. Invalid membership type. Please contact support.",
                    "access_token": "",
                    "error": "invalid_membership_type",
                    "membership_status": membership_status,
                    "membership_type": membership_type,
                },
            )

        print(
            f"✅ Membership validation passed for token refresh - Status: {membership_status}, Type: {membership_type}"
        )

        # Generate new access token
        token_data = {
            "sub": str(user["_id"]),
            "phone": user["phone"],
            "email": user["email"],
            "role": user["role"],
            "membership_status": user.get("membership_status", "inactive"),
            "subscription_id": user.get("subscription_id", None),
            "stripe_customer_id": user.get("stripe_customer_id", None),
            "full_name": user.get("full_name", ""),
        }

        # Get club count for both captains and members
        club_count = 0
        if user["role"] == "Captain":
            try:
                from ..utils import get_club_count_for_captain, update_user_club_count

                club_count = await get_club_count_for_captain(str(user["_id"]))
                # Update the user's club count in the database
                await update_user_club_count(str(user["_id"]), club_count)
                print(
                    f"👑 Captain {user['full_name']} has {club_count} clubs (refresh token)"
                )
            except Exception as e:
                print(f"⚠️ Could not get club count for captain during refresh: {e}")
                # Use stored club count if available
                club_count = user.get("club_count", 0)
        elif user["role"] == "Member":
            try:
                from ..utils import get_club_count_for_member, update_user_club_count

                club_count = await get_club_count_for_member(str(user["_id"]))
                # Update the user's club count in the database
                await update_user_club_count(str(user["_id"]), club_count)
                print(
                    f"👤 Member {user['full_name']} has {club_count} clubs (refresh token)"
                )
            except Exception as e:
                print(f"⚠️ Could not get club count for member during refresh: {e}")
                # Use stored club count if available
                club_count = user.get("club_count", 0)

        new_access_token = create_access_token(
            data=token_data, remember_me=False, club_count=club_count
        )

        # Prepare user data for response
        user_data = {
            "id": str(user["_id"]),
            "full_name": user["full_name"],
            "email": user["email"],
            "phone": user["phone"],
            "role": user["role"],
            "created_at": (
                user["created_at"].isoformat() if user.get("created_at") else None
            ),
            "membership_status": user.get("membership_status", "inactive"),
        }

        response_data = {
            "message": "Token refreshed successfully",
            "access_token": new_access_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES,
            "user": user_data,
        }

        print(f"✅ Token refresh successful for user: {user_id}")
        return response_data

    except Exception as e:
        print(f"❌ Token refresh error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Internal server error during token refresh",
                "access_token": "",
                "error": str(e),
            },
        )
