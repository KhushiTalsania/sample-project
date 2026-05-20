from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from services.auth.utils import validate_social_token

from ..models import (
    SocialLoginRequest,
    SocialLoginResponse,
    ProfileCompletionRequest,
    ProfileCompletionResponse,
    ModeratorProfileCompletionRequest,
)
from ..utils import (
    find_or_create_social_user,
    log_social_login_attempt,
    create_access_token,
    create_refresh_token,
    get_user_collection,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from datetime import datetime
from bson import ObjectId

router = APIRouter()


@router.post("/auth/social-login", response_model=SocialLoginResponse)
async def social_login(request: SocialLoginRequest):
    try:
        print(f"🔍 Starting social login for provider: {request.provider}")
        print(
            f"🔍 Access token length: {len(request.access_token) if request.access_token else 0}"
        )

        # Validate social token
        try:
            profile = await validate_social_token(
                request.access_token, request.provider
            )
            print(f"✅ Token validation successful: {profile}")
        except Exception as token_error:
            print(f"❌ Token validation failed: {str(token_error)}")
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error=f"Token validation failed: {str(token_error)}",
            )
            return SocialLoginResponse(
                message="Invalid or expired token",
                success=False,
                expires_in=0,
                error=f"Token validation failed: {str(token_error)}",
            )

        if not profile:
            await log_social_login_attempt(
                provider=request.provider, success=False, error="Invalid token"
            )
            return SocialLoginResponse(
                message="Invalid or expired token",
                success=False,
                expires_in=0,
                error="Invalid token",
            )

        # Find existing user (new users are not allowed to sign in directly)
        try:
            print(f"🔍 Looking for existing user with profile: {profile}")
            user = await find_or_create_social_user(profile)
            print(
                f"✅ User found/created successfully: {user.get('_id') if user else 'None'}"
            )
        except HTTPException as e:
            print(
                f"❌ HTTP Exception in find_or_create_social_user: {e.status_code} - {e.detail}"
            )
            if e.status_code == 403:
                # User needs to subscribe first - return clean message
                await log_social_login_attempt(
                    provider=request.provider,
                    success=False,
                    error="New user - subscription required",
                )
                return SocialLoginResponse(
                    message="Please complete your subscription first.",
                    success=False,
                    expires_in=0,
                    error="Please complete your subscription first.",
                )
            else:
                # Re-raise other HTTP exceptions
                raise e
        except Exception as e:
            print(f"❌ Unexpected error in find_or_create_social_user: {str(e)}")
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error=f"Unexpected error: {str(e)}",
            )
            return SocialLoginResponse(
                message="An unexpected error occurred while processing social login",
                success=False,
                expires_in=0,
                error=f"Unexpected error: {str(e)}",
            )

        # At this point, user exists and has valid membership (checked in find_or_create_social_user)
        membership_status = user.get("membership_status")
        membership_type = user.get("membership_type")

        print(
            f"✅ Social login user - Membership Status: {membership_status}, Type: {membership_type}"
        )

        # Check if user is deleted, inactive or temporarily deactivated
        user_status = user.get("status", "active")
        is_permanent_deactivate = user.get("is_permanent_deactivate", False)
        is_deleted_temp_admin = user.get("is_deleted_temp_admin", False)
        is_deleted_per_admin = user.get("is_deleted_per_admin", False)

        # Simple OR: block login if ANY of these flags is true
        if is_permanent_deactivate or is_deleted_temp_admin or is_deleted_per_admin:
            if is_permanent_deactivate:
                print(f"❌ Social login blocked - User is temporarily deactivated")
                await log_social_login_attempt(
                    provider=request.provider,
                    success=False,
                    error="Account temporarily deactivated",
                )
                return SocialLoginResponse(
                    message="Access denied. Your account is temporarily deactivated. Please reactivate your account to continue.",
                    success=False,
                    expires_in=0,
                    error="account_temporarily_deactivated",
                )
            if is_deleted_temp_admin:
                print(
                    f"❌ Social login blocked - User has been temporarily deleted by admin"
                )
                await log_social_login_attempt(
                    provider=request.provider,
                    success=False,
                    error="Account temporarily deleted by admin",
                )
                return SocialLoginResponse(
                    message="Access denied. Your account has been temporarily suspended by admin. Please contact support.",
                    success=False,
                    expires_in=0,
                    error="account_temporarily_deleted_admin",
                )
            print(f"❌ Social login blocked - User permanently deleted by admin")
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error="Account permanently deleted by admin",
            )
            return SocialLoginResponse(
                message="Access denied. Your account has been permanently suspended by admin. Please contact support.",
                success=False,
                expires_in=0,
                error="account_deleted_admin",
            )

        # Block login for inactive users ONLY if deleted by admin (temp or permanent)
        if user_status == "inactive" and (
            is_deleted_temp_admin or is_deleted_per_admin
        ):
            print(f"❌ Social login blocked - User is inactive due to admin deletion")
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error="Account inactive due to admin deletion",
            )
            return SocialLoginResponse(
                message="Access denied. Your account is inactive due to admin action. Please contact support.",
                success=False,
                expires_in=0,
                error="account_inactive_admin",
            )

        # Block login for deleted users
        if user_status == "deleted" or membership_status == "deleted":
            print(f"❌ Social login blocked - User has been permanently deleted")
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error="Account permanently deleted",
            )
            return SocialLoginResponse(
                message="Access denied. Your account has been permanently deleted.",
                success=False,
                expires_in=0,
                error="account_deleted",
            )

        # Block login for temporarily deactivated users
        if is_permanent_deactivate:
            # If also inactive due to admin deletion, unify response with inactive-admin handling
            is_deleted_per_admin = user.get("is_deleted_per_admin", False)
            if user_status == "inactive" and (
                is_deleted_temp_admin or is_deleted_temp_admin
            ):
                print(
                    f"❌ Social login blocked - User is inactive due to admin deletion (permanent deactivate)"
                )
                await log_social_login_attempt(
                    provider=request.provider,
                    success=False,
                    error="Account inactive due to admin deletion",
                )
                return SocialLoginResponse(
                    message="Access denied. Your account is inactive due to admin action. Please contact support.",
                    success=False,
                    expires_in=0,
                    error="account_inactive_admin",
                )
            print(f"❌ Social login blocked - User is temporarily deactivated")
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error="Account temporarily deactivated",
            )
            return SocialLoginResponse(
                message="Access denied. Your account is temporarily deactivated. Please reactivate your account to continue.",
                success=False,
                expires_in=0,
                error="account_temporarily_deactivated",
            )

        # Block login for users temporarily deleted by admin
        if is_deleted_temp_admin:
            print(
                f"❌ Social login blocked - User has been temporarily deleted by admin"
            )
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error="Account temporarily deleted by admin",
            )
            return SocialLoginResponse(
                message="Access denied. Your account has been temporarily suspended by admin. Please contact support.",
                success=False,
                expires_in=0,
                error="account_temporarily_deleted_admin",
            )

        # For social login users, profile is automatically completed
        # No additional input required from user
        is_social_user = user.get("is_social_login", False)
        requires_profile_completion = False  # Always false for social login users
        is_completed_profile = True  # Always true for social login users

        # Note: last_login is already updated in find_or_create_social_user function

        # Always generate tokens for social login users
        # Profile is automatically completed, so always generate tokens
        try:
            # Generate tokens for social login users
            token_data = {
                "sub": str(user["_id"]),
                "email": user.get("email"),
                "role": user.get("role"),
                "provider": request.provider,
                "full_name": user.get("full_name", ""),
            }
            print(f"🔍 Generating tokens with data: {token_data}")

            # Get club count for both captains and members
            club_count = 0
            if user.get("role") == "Captain":
                try:
                    from ..utils import (
                        get_club_count_for_captain,
                        update_user_club_count,
                    )

                    club_count = await get_club_count_for_captain(str(user["_id"]))
                    # Update the user's club count in the database
                    await update_user_club_count(str(user["_id"]), club_count)
                    print(
                        f"👑 Captain {user.get('full_name', 'Unknown')} has {club_count} clubs"
                    )
                except Exception as e:
                    print(f"⚠️ Could not get club count for captain: {e}")
                    # Use stored club count if available
                    club_count = user.get("club_count", 0)
            elif user.get("role") == "Member":
                try:
                    from ..utils import (
                        get_club_count_for_member,
                        update_user_club_count,
                    )

                    club_count = await get_club_count_for_member(str(user["_id"]))
                    # Update the user's club count in the database
                    await update_user_club_count(str(user["_id"]), club_count)
                    print(
                        f"👤 Member {user.get('full_name', 'Unknown')} has {club_count} clubs"
                    )
                except Exception as e:
                    print(f"⚠️ Could not get club count for member: {e}")
                    # Use stored club count if available
                    club_count = user.get("club_count", 0)

            # For Captain role, validate Stripe Connect account status - BLOCK login if incomplete
            if user.get("role") == "Captain":
                try:
                    import stripe
                    import os
                    from services.club.stripe_connect_service import StripeConnectService
                    
                    stripe_connect_service = StripeConnectService()
                    stripe_connect_account_id = user.get("stripe_connect_account_id")
                    
                    if stripe_connect_account_id:
                        print(f"🔍 Validating Stripe Connect account for Captain (Social Login): {stripe_connect_account_id}")
                        
                        # Retrieve account from Stripe
                        account = stripe.Account.retrieve(stripe_connect_account_id)
                        
                        charges_enabled = account.charges_enabled
                        payouts_enabled = account.payouts_enabled
                        details_submitted = account.details_submitted
                        
                        # Check if account can process and receive funds
                        if not (charges_enabled and payouts_enabled):
                            # Account not ready - BLOCK LOGIN
                            print(f"❌ Social login blocked - Stripe Connect account not ready")
                            print(f"   Account ID: {stripe_connect_account_id}")
                            print(f"   charges_enabled: {charges_enabled}, payouts_enabled: {payouts_enabled}, details_submitted: {details_submitted}")
                            
                            # Create remediation link
                            stripe_onboarding_url = None
                            try:
                                print(f"🔗 Creating Stripe AccountLink for account: {stripe_connect_account_id}")
                                
                                link_type = 'account_onboarding' if not details_submitted else 'account_update'
                                print(f"   Link type: {link_type}")
                                
                                account_link = stripe.AccountLink.create(
                                    account=stripe_connect_account_id,
                                    refresh_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                                    return_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                                    type=link_type,
                                )
                                
                                stripe_onboarding_url = account_link.url
                                print(f"✅ Successfully created remediation URL: {stripe_onboarding_url}")
                                
                            except Exception as link_error:
                                print(f"❌ Error creating AccountLink: {str(link_error)}")
                            
                            # Determine error message
                            if not details_submitted:
                                error_message = "Your Stripe Connect account onboarding is incomplete. Please complete the verification process to access your Captain account."
                                stripe_status = "pending_onboarding"
                            else:
                                error_message = "Your Stripe Connect account requires additional verification. Please complete the required steps to access your Captain account."
                                stripe_status = "restricted"
                            
                            # Log failed attempt
                            await log_social_login_attempt(
                                provider=request.provider,
                                success=False,
                                error="Stripe verification required",
                            )
                            
                            # Return error response with remediation link - 403 Forbidden
                            return JSONResponse(
                                status_code=403,
                                content={
                                    "message": error_message,
                                    "success": False,
                                    "expires_in": 0,
                                    "error": "stripe_verification_required",
                                    "stripe_connect_account_id": stripe_connect_account_id,
                                    "stripe_onboarding_url": stripe_onboarding_url,
                                    "stripe_connect_status": stripe_status,
                                    "charges_enabled": charges_enabled,
                                    "payouts_enabled": payouts_enabled,
                                    "details_submitted": details_submitted,
                                    "remediation_required": True,
                                    "remediation_message": "Please click the link below to complete your Stripe Connect verification and enable login." if stripe_onboarding_url else f"Please contact support with account ID: {stripe_connect_account_id}"
                                }
                            )
                        else:
                            print(f"✅ Stripe Connect account verified for Captain (Social Login)")
                    
                    else:
                        # Captain has no Stripe Connect account - Create one
                        print(f"⚠️ Captain has no Stripe Connect account - Creating one")
                        
                        try:
                            connect_result = await stripe_connect_service.create_captain_connect_account(
                                captain_id=str(user["_id"]),
                                captain_email=user.get("email"),
                                captain_name=user.get("full_name"),
                                country='US'
                            )
                            
                            if connect_result.get("success"):
                                stripe_connect_account_id = connect_result.get("account_id")
                                stripe_onboarding_url = connect_result.get("onboarding_url")
                                
                                print(f"✅ Stripe Connect account created: {stripe_connect_account_id}")
                                
                                # Block login and return onboarding URL - 403 Forbidden
                                await log_social_login_attempt(
                                    provider=request.provider,
                                    success=False,
                                    error="Stripe onboarding required for new Captain",
                                )
                                
                                return JSONResponse(
                                    status_code=403,
                                    content={
                                        "message": "Your Captain account has been created. Please complete Stripe Connect onboarding to start receiving payments.",
                                        "success": False,
                                        "expires_in": 0,
                                        "error": "stripe_onboarding_required",
                                        "stripe_connect_account_id": stripe_connect_account_id,
                                        "stripe_onboarding_url": stripe_onboarding_url,
                                        "stripe_connect_status": "pending_onboarding",
                                        "charges_enabled": False,
                                        "payouts_enabled": False,
                                        "details_submitted": False,
                                        "remediation_required": True,
                                        "remediation_message": "Please complete Stripe Connect onboarding to enable Captain login."
                                    }
                                )
                            else:
                                print(f"⚠️ Failed to create Stripe Connect account: {connect_result.get('error')}")
                                # Continue with login but note the issue
                        
                        except Exception as create_error:
                            print(f"⚠️ Error creating Stripe Connect account: {str(create_error)}")
                            # Continue with login but note the issue
                
                except Exception as stripe_validation_error:
                    print(f"⚠️ Error during Stripe validation: {str(stripe_validation_error)}")
                    # Don't block login for validation errors - continue
            
            access_token = create_access_token(data=token_data, club_count=club_count)
            refresh_token = create_refresh_token(token_data)
            expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60

            print(
                f"✅ Tokens generated successfully - Access token length: {len(access_token) if access_token else 0}"
            )
        except Exception as token_gen_error:
            print(f"❌ Error generating tokens: {str(token_gen_error)}")
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error=f"Token generation failed: {str(token_gen_error)}",
            )
            return SocialLoginResponse(
                message="Failed to generate authentication tokens",
                success=False,
                expires_in=0,
                error=f"Token generation failed: {str(token_gen_error)}",
            )

        # Prepare user data
        # For social login users, profile is always completed
        try:
            user_data = {
                "id": str(user["_id"]),
                "full_name": user["full_name"],
                "first_name": user.get("first_name", ""),
                "last_name": user.get("last_name", ""),
                "email": user.get("email"),
                "phone": user.get("phone") or "",
                "role": user.get("role") or "Member",  # Default to Member if not set
                "profile_picture": user.get("profile_picture"),
                "email_verified": user.get(
                    "email_verified", True
                ),  # Social login users are verified
                "is_profile_completed": True,  # Always true for social login users
                "is_social_login": user.get("is_social_login", False),
                "social_logins": user.get("social_logins", []),
                "created_at": (
                    user.get("created_at").isoformat()
                    if user.get("created_at")
                    else None
                ),
                "last_login": (
                    user.get("last_login").isoformat()
                    if user.get("last_login")
                    else None
                ),
                "membership_status": user.get(
                    "membership_status", "active"
                ),  # Default to active
                "membership_type": user.get(
                    "membership_type", "trial"
                ),  # Default to trial
                "subscription_id": user.get("subscription_id", None),
                "stripe_customer_id": user.get("stripe_customer_id", None),
                "complete_step": 1,  # Default to step 1 (profile completed)
            }
            print(f"✅ User data prepared successfully: {user_data}")
        except Exception as user_data_error:
            print(f"❌ Error preparing user data: {str(user_data_error)}")
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error=f"User data preparation failed: {str(user_data_error)}",
            )
            return SocialLoginResponse(
                message="Failed to prepare user data",
                success=False,
                expires_in=0,
                error=f"User data preparation failed: {str(user_data_error)}",
            )

        # Log successful login attempt
        await log_social_login_attempt(
            provider=request.provider, success=True, user_id=str(user["_id"])
        )

        # Create user session for the generated access token
        try:
            from ..utils import create_user_session

            await create_user_session(
                str(user["_id"]), access_token, f"Social Login - {request.provider}"
            )
            print(f"✅ Session created for social login user: {user['_id']}")
        except Exception as session_error:
            print(
                f"⚠️ Failed to create session for social login user: {str(session_error)}"
            )
            # Don't fail the login if session creation fails

        # Update both access_token and refresh_token in database
        # If tokens already exist, they will be updated with new ones
        try:
            users_collection = get_user_collection()
            await users_collection.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "token_created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            print(
                f"✅ Tokens updated in database for user {user['_id']} (existing tokens replaced with new ones)"
            )
        except Exception as token_save_error:
            print(f"⚠️ Failed to update tokens in database: {str(token_save_error)}")
            # Don't fail the login if token updating fails

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
                        from datetime import timezone
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

        # For social login users, profile is always completed
        message = "Social login successful! Profile completed automatically."

        # Always return generated tokens for social login users
        try:
            response_access_token = access_token
            response_refresh_token = refresh_token

            print(f"🔍 Creating final response with tokens and user data")

            response = SocialLoginResponse(
                message=message,
                success=True,  # Always true for social login users
                access_token=response_access_token,
                refresh_token=response_refresh_token,
                token_type="bearer",
                expires_in=expires_in,
                user=user_data,
                is_new_user=True,  # Social login users are not new users
                requires_role_selection=False,  # Deprecated, using is_completed_profile instead
                is_completed_profile=True,  # Always true for social login users
                membership_status=membership_status,
                membership_type=membership_type,
            )

            print(f"✅ Response created successfully")
            return response

        except Exception as response_error:
            print(f"❌ Error creating response: {str(response_error)}")
            await log_social_login_attempt(
                provider=request.provider,
                success=False,
                error=f"Response creation failed: {str(response_error)}",
            )
            return SocialLoginResponse(
                message="Failed to create response",
                success=False,
                expires_in=0,
                error=f"Response creation failed: {str(response_error)}",
            )

    except HTTPException as e:
        await log_social_login_attempt(
            provider=request.provider, success=False, error=str(e.detail)
        )
        return SocialLoginResponse(
            message=str(e.detail), success=False, expires_in=0, error=str(e.detail)
        )
    except Exception as e:
        await log_social_login_attempt(
            provider=request.provider, success=False, error=str(e)
        )
        return SocialLoginResponse(
            message="Internal server error",
            success=False,
            expires_in=0,
            error="Internal server error",
        )


# @router.get("/auth/social-providers")
# async def get_social_providers():
#     """
#     Get available social login providers and their configuration
#     """
#     return {
#         "providers": [
#             {
#                 "name": "google",
#                 "display_name": "Google",
#                 "icon": "google-icon",
#                 "color": "#4285F4",
#                 "enabled": True
#             },
#             {
#                 "name": "apple",
#                 "display_name": "Apple",
#                 "icon": "apple-icon",
#                 "color": "#000000",
#                 "enabled": True
#             }
#             # {
#             #     "name": "facebook",
#             #     "display_name": "Facebook",
#             #     "icon": "facebook-icon",
#             #     "color": "#1877F2",
#             #     "enabled": True
#             # }
#         ],
#         "message": "Available social login providers"
#     }

# @router.post("/auth/link-social-account")
# async def link_social_account(request: SocialLoginRequest):
#     """
#     Link a social account to an existing user account
#     """
#     try:
#         # This endpoint would require authentication to link accounts
#         # For now, we'll return a placeholder response
#         return {
#             "message": "Social account linking functionality coming soon",
#             "success": False,
#             "error": "Not implemented yet"
#         }
#     except Exception as e:
#         return JSONResponse(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             content={
#                 "message": "Internal server error",
#                 "success": False,
#                 "error": str(e)
#             }
#         )

# @router.delete("/auth/unlink-social-account")
# async def unlink_social_account(provider: str, user_id: str):
#     """
#     Unlink a social account from user account
#     """
#     try:
#         # This endpoint would require authentication to unlink accounts
#         # For now, we'll return a placeholder response
#         return {
#             "message": "Social account unlinking functionality coming soon",
#             "success": False,
#             "error": "Not implemented yet"
#         }
#     except Exception as e:
#         return JSONResponse(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             content={
#                 "message": "Internal server error",
#                 "success": False,
#                 "error": str(e)
#             }
#         )


@router.post("/auth/complete-profile", response_model=ProfileCompletionResponse)
async def complete_profile(request: ProfileCompletionRequest):
    """
    Complete user profile by selecting role and providing phone number
    """
    try:
        users_collection = get_user_collection()

        # Validate user exists
        user = await users_collection.find_one({"_id": ObjectId(request.user_id)})
        if not user:
            return ProfileCompletionResponse(
                message="User not found",
                success=False,
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                user={},
            )

        # Validate phone number format
        if not request.phone.isdigit() or not (7 <= len(request.phone) <= 15):
            return ProfileCompletionResponse(
                message="Invalid phone number format",
                success=False,
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                user={},
            )

        # Update user profile
        update_fields = {
            "role": request.role,
            "phone": request.phone,
            "is_profile_completed": True,
        }

        await users_collection.update_one(
            {"_id": ObjectId(request.user_id)}, {"$set": update_fields}
        )

        # Send profile completion email
        try:
            from ..utils import send_email

            email_subject = "Profile Completed Successfully - MVP Sports"
            email_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <div style="background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
                        <h1 style="margin: 0;">🎉 Profile Completed!</h1>
                    </div>
                    
                    <div style="background-color: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px;">
                        <h2 style="color: #4CAF50; margin-top: 0;">Welcome to MVP Sports, {user.get('full_name', 'there')}!</h2>
                        
                        <p>Your profile has been completed successfully. Here are your account details:</p>
                        
                        <div style="background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4CAF50;">
                            <h3 style="margin-top: 0; color: #4CAF50;">Account Information</h3>
                            <p><strong>Full Name:</strong> {user.get('full_name', 'N/A')}</p>
                            <p><strong>Email:</strong> {user.get('email', 'N/A')}</p>
                            <p><strong>Phone:</strong> {request.phone}</p>
                            <p><strong>Role:</strong> {request.role}</p>
                            <p><strong>Membership Status:</strong> {user.get("membership_status", "Active")}</p>
                            <p><strong>Membership Type:</strong> {user.get("membership_type", "Trial")}</p>
                            <p><strong>Login Method:</strong> Social Login</p>
                        </div>
                        
                        <div style="background-color: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0;">
                            <h3 style="margin-top: 0; color: #2e7d32;">What's Next?</h3>
                            <ul style="margin: 0; padding-left: 20px;">
                                <li>You can now access all features of MVP Sports</li>
                                <li>Explore different betting clubs and join communities</li>
                                <li>Connect with other members and captains</li>
                                <li>Start your betting journey with expert guidance</li>
                            </ul>
                        </div>
                        
                        <div style="background-color: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
                            <h3 style="margin-top: 0; color: #856404;">Security Reminder</h3>
                            <p style="margin-bottom: 0;">Your account is secured through social login. You can continue using your social account to access MVP Sports. If you need to change your login method, please contact support.</p>
                        </div>
                        
                        <p style="text-align: center; margin-top: 30px;">
                            <strong>Thank you for choosing MVP Sports!</strong><br>
                            We're excited to have you as part of our community.
                        </p>
                        
                        <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                            <p style="color: #666; font-size: 14px;">
                                Best regards,<br>
                                <strong>MVP Sports Team</strong><br>
                                <a href="mailto:support@mvpsports.com" style="color: #4CAF50;">support@mvpsports.com</a>
                            </p>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """

            await send_email(
                to_email=user.get("email"),
                subject=email_subject,
                html_content=email_body,
            )
            print(f"✅ Profile completion email sent to: {user.get('email')}")

        except Exception as email_error:
            print(f"⚠️ Failed to send profile completion email: {str(email_error)}")
            # Don't fail the profile completion if email fails

        # Generate JWT tokens
        token_data = {
            "sub": request.user_id,
            "email": user.get("email"),
            "role": request.role,
            "provider": "social",
            "full_name": user.get("full_name", ""),
        }

        # Get club count for both captains and members
        club_count = 0
        if request.role == "Captain":
            try:
                from ..utils import get_club_count_for_captain, update_user_club_count

                club_count = await get_club_count_for_captain(request.user_id)
                # Update the user's club count in the database
                await update_user_club_count(request.user_id, club_count)
                print(
                    f"👑 Captain {user.get('full_name', 'Unknown')} has {club_count} clubs (complete-profile)"
                )
            except Exception as e:
                print(
                    f"⚠️ Could not get club count for captain during complete-profile: {e}"
                )
                # Use stored club count if available
                club_count = user.get("club_count", 0)
        elif request.role == "Member":
            try:
                from ..utils import get_club_count_for_member, update_user_club_count

                club_count = await get_club_count_for_member(request.user_id)
                # Update the user's club count in the database
                await update_user_club_count(request.user_id, club_count)
                print(
                    f"👤 Member {user.get('full_name', 'Unknown')} has {club_count} clubs (complete-profile)"
                )
            except Exception as e:
                print(
                    f"⚠️ Could not get club count for member during complete-profile: {e}"
                )
                # Use stored club count if available
                club_count = user.get("club_count", 0)

        access_token = create_access_token(data=token_data, club_count=club_count)
        refresh_token = create_refresh_token(token_data)
        expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60

        # Use provided tokens if available, otherwise use generated ones
        response_access_token = (
            request.access_token if request.access_token else access_token
        )
        response_refresh_token = (
            request.refresh_token if request.refresh_token else refresh_token
        )

        # Initialize Stripe Connect variables
        stripe_connect_account_id = None
        stripe_onboarding_url = None
        stripe_connect_status = None
        
        # For Captain role, create Stripe Connect account
        if request.role == "Captain":
            try:
                # Import Stripe Connect service
                from services.club.stripe_connect_service import StripeConnectService
                
                stripe_connect_service = StripeConnectService()
                
                # Create Stripe Connect account for the Captain
                print(f"🚀 Creating Stripe Connect account for Captain (Social Login): {user.get('email')}")
                
                connect_result = await stripe_connect_service.create_captain_connect_account(
                    captain_id=str(user["_id"]),
                    captain_email=user.get("email"),
                    captain_name=user.get("full_name"),
                    country='US'  # Default country, can be made configurable
                )
                
                if connect_result.get("success"):
                    stripe_connect_account_id = connect_result.get("account_id")
                    stripe_onboarding_url = connect_result.get("onboarding_url")
                    stripe_connect_status = connect_result.get("status", "pending_onboarding")
                    
                    print(f"✅ Stripe Connect account created for Captain {str(user['_id'])}")
                    print(f"   Account ID: {stripe_connect_account_id}")
                    print(f"   Onboarding URL: {stripe_onboarding_url}")
                else:
                    print(f"⚠️ Failed to create Stripe Connect account: {connect_result.get('error')}")
                    # Don't fail profile completion if Stripe Connect setup fails
                    
            except Exception as stripe_error:
                print(f"⚠️ Error creating Stripe Connect account for Captain: {str(stripe_error)}")
                # Don't fail profile completion if Stripe Connect setup fails

        # Prepare user data
        user_data = {
            "user_id": str(user["_id"]),
            "full_name": user["full_name"],
            "email": user.get("email"),
            "phone": request.phone,
            "role": request.role,
            "membership_status": user.get("membership_status", "inactive"),
            "membership_type": user.get("membership_type", "none"),
            "wants_membership": user.get("wants_membership", False),
            "terms_accepted": user.get("terms_accepted", False),
            "terms_accepted_at": user.get("terms_accepted_at"),
            "subscription_id": user.get("subscription_id"),
            "stripe_customer_id": user.get("stripe_customer_id"),
            "profile_picture": user.get("profile_picture"),
            "email_verified": user.get(
                "email_verified", True
            ),  # Social login users are verified
            "is_profile_completed": True,
            "is_social_login": user.get("is_social_login", False),
            "social_logins": user.get("social_logins", []),
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
            "last_login": user.get("last_login"),
        }
        
        # Add Stripe Connect info to user data if Captain
        if stripe_connect_account_id:
            user_data["stripe_connect_account_id"] = stripe_connect_account_id
            user_data["stripe_connect_status"] = stripe_connect_status

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
                        from datetime import timezone
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
                # Don't fail profile completion if token registration fails

        return ProfileCompletionResponse(
            message="Profile completed successfully" if request.role != "Captain" else "Profile completed successfully. Please complete Stripe onboarding to start receiving payments.",
            success=True,
            access_token=response_access_token,
            refresh_token=response_refresh_token,
            token_type="bearer",
            expires_in=expires_in,
            user=user_data,
            is_completed_profile=True,
            # Stripe Connect fields (will be None for Members)
            stripe_connect_account_id=stripe_connect_account_id,
            stripe_onboarding_url=stripe_onboarding_url,
            stripe_connect_status=stripe_connect_status,
            # FCM token fields
            fcm_token=request.fcm_token if request.fcm_token else None,
            device_type=request.device_type if request.device_type else None,
            device_name=request.device_name if request.device_name else None,
            device_id=request.device_id if request.device_id else None,
        )

    except Exception as e:
        return ProfileCompletionResponse(
            message=f"Failed to complete profile: {str(e)}",
            success=False,
            access_token="",
            refresh_token="",
            token_type="bearer",
            expires_in=0,
            user={},
        )


@router.post(
    "/auth/complete-moderator-profile", response_model=ProfileCompletionResponse
)
async def complete_moderator_profile(request: ModeratorProfileCompletionRequest):
    """
    Complete moderator profile using signup token.
    This endpoint is for moderators who were invited via email and need to complete their signup.
    No payment required - moderators get free access.
    """
    try:
        print(
            f"🔍 Starting moderator profile completion for token: {request.signup_token[:20]}..."
        )

        # Import the club step4 service to validate the token
        from services.club.club_step4_service import club_step4_service

        # Validate the moderator signup token
        validation_result = await club_step4_service.validate_moderator_signup_token(
            request.signup_token
        )

        if not validation_result["valid"]:
            return ProfileCompletionResponse(
                message=validation_result["error"],
                success=False,
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                user={},
            )

        print(
            f"✅ Token validation successful for email: {validation_result['payload']['email']}"
        )

        # Get user collection
        users_collection = get_user_collection()

        # Find user by email from token payload
        user_email = validation_result["payload"]["email"]
        user = await users_collection.find_one({"email": user_email})

        print(f"🔍 User lookup for {user_email}: {'Found' if user else 'Not Found'}")
        if user:
            print(
                f"🔍 User details - Role: {user.get('role')}, Is Register: {user.get('is_register')}, Status: {user.get('status')}"
            )

        if not user:
            return ProfileCompletionResponse(
                message="User not found",
                success=False,
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                user={},
            )

        # Validate user role is moderator
        if user.get("role") != "moderator":
            return ProfileCompletionResponse(
                message="User is not eligible for moderator signup",
                success=False,
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                user={},
            )

        # Check if user is already registered
        if user.get("is_register", False):
            return ProfileCompletionResponse(
                message="User has already completed signup",
                success=False,
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                user={},
            )

        # Validate user status is inactive (expected for unregistered moderators)
        if user.get("status") != "inactive":
            return ProfileCompletionResponse(
                message="User status is not eligible for signup",
                success=False,
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                user={},
            )

        print(
            f"✅ User validation passed - Role: {user.get('role')}, Is Register: {user.get('is_register')}, Status: {user.get('status')}"
        )

        # Validate phone number format
        if not request.phone.isdigit() or not (7 <= len(request.phone) <= 15):
            return ProfileCompletionResponse(
                message="Phone number must be between 7 and 15 characters long",
                success=False,
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                user={},
            )

        # Hash password
        from ..utils import hash_password

        hashed_password = hash_password(request.password)

        # Complete the moderator signup
        signup_data = {
            "full_name": f"{request.first_name} {request.last_name}".strip(),
            "password": request.password,
        }

        complete_result = await club_step4_service.complete_moderator_signup(
            request.signup_token, signup_data
        )

        if not complete_result["success"]:
            return ProfileCompletionResponse(
                message=complete_result["error"],
                success=False,
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                user={},
            )

        print(f"✅ Moderator signup completed for: {user_email}")

        # Update additional profile fields
        full_name = f"{request.first_name} {request.last_name}".strip()
        formatted_phone = f"{request.country_code}{request.phone}"

        update_fields = {
            "first_name": request.first_name,
            "last_name": request.last_name,
            "phone": formatted_phone,
            "country_code": request.country_code,
            "password_hash": hashed_password,
            "profile_completed": True,
            "profile_completed_at": datetime.utcnow(),
            "complete_step": 1,
            "updated_at": datetime.utcnow(),
            "is_auto_created": False,
            "is_register": True,
            "signup_token": None,
        }

        await users_collection.update_one({"_id": user["_id"]}, {"$set": update_fields})

        print(f"✅ Moderator profile updated for: {user_email}")

        # Send profile completion email
        try:
            from ..utils import send_email

            email_subject = "Welcome to MVP Sports - Moderator Account Activated!"
            email_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <div style="background-color: #e74c3c; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
                        <h1 style="margin: 0;">🎉 Moderator Account Activated!</h1>
                    </div>
                    
                    <div style="background-color: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px;">
                        <h2 style="color: #e74c3c; margin-top: 0;">Welcome to MVP Sports, {full_name}!</h2>
                        
                        <p>Your moderator account has been successfully activated. You now have special privileges to help manage betting clubs.</p>
                        
                        <div style="background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #e74c3c;">
                            <h3 style="margin-top: 0; color: #e74c3c;">Account Information</h3>
                            <p><strong>Full Name:</strong> {full_name}</p>
                            <p><strong>Email:</strong> {user_email}</p>
                            <p><strong>Phone:</strong> {formatted_phone}</p>
                            <p><strong>Role:</strong> Moderator</p>
                            <p><strong>Membership Status:</strong> Active (Free)</p>
                            <p><strong>Account Type:</strong> Moderator - No Payment Required</p>
                        </div>
                        
                        <div style="background-color: #fef9e7; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #f39c12;">
                            <h3 style="margin-top: 0; color: #d68910;">Moderator Privileges</h3>
                            <ul style="margin: 0; padding-left: 20px;">
                                <li>Help manage betting clubs and communities</li>
                                <li>Monitor member activities and ensure fair play</li>
                                <li>Assist captains with club administration</li>
                                <li>Access moderator dashboard and tools</li>
                                <li>Free access to all platform features</li>
                            </ul>
                        </div>
                        
                        <div style="background-color: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0;">
                            <h3 style="margin-top: 0; color: #2e7d32;">What's Next?</h3>
                            <ul style="margin: 0; padding-left: 20px;">
                                <li>Log in to your moderator dashboard</li>
                                <li>Review assigned clubs and responsibilities</li>
                                <li>Connect with club captains and members</li>
                                <li>Start helping maintain club quality and fairness</li>
                            </ul>
                        </div>
                        
                        <div style="background-color: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
                            <h3 style="margin-top: 0; color: #856404;">Security Reminder</h3>
                            <p style="margin-bottom: 0;">Your moderator account is now active. Please keep your login credentials secure and report any suspicious activity immediately.</p>
                        </div>
                        
                        <p style="text-align: center; margin-top: 30px;">
                            <strong>Thank you for joining MVP Sports as a Moderator!</strong><br>
                            We appreciate your commitment to maintaining a fair and enjoyable betting environment.
                        </p>
                        
                        <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                            <p style="color: #666; font-size: 14px;">
                                Best regards,<br>
                                <strong>MVP Sports Team</strong><br>
                                <a href="mailto:support@mvpsports.com" style="color: #e74c3c;">support@mvpsports.com</a>
                            </p>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """

            await send_email(
                to_email=user_email, subject=email_subject, html_content=email_body
            )
            print(f"✅ Moderator profile completion email sent to: {user_email}")

        except Exception as email_error:
            print(
                f"⚠️ Failed to send moderator profile completion email: {str(email_error)}"
            )
            # Don't fail the profile completion if email fails

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
                        f"✅ FCM token {action} for moderator {user_id_str}: {token_result.get('message')}"
                    )
                else:
                    print(
                        f"⚠️ Failed to register FCM token via helper: {token_result.get('error')}"
                    )
                    # Fallback: create or update token directly
                    try:
                        collections = get_collections()
                        tokens_col = collections.get_user_tokens_collection()
                        from datetime import timezone
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
                                f"✅ Updated existing FCM token directly for moderator {user_id_str}"
                            )
                        else:
                            doc = {
                                "user_id": user_id_str,
                                "created_at": now,
                                **payload,
                            }
                            await tokens_col.insert_one(doc)
                            print(
                                f"✅ Created FCM token directly for moderator {user_id_str} (fallback)"
                            )
                    except Exception as fallback_error:
                        print(f"⚠️ Error handling FCM token fallback: {str(fallback_error)}")
            except Exception as token_error:
                print(f"⚠️ Error registering FCM token: {str(token_error)}")
                # Don't fail profile completion if token registration fails

        # Generate JWT tokens
        token_data = {
            "sub": str(user["_id"]),
            "email": user_email,
            "role": "moderator",
            "provider": "direct",
            "full_name": full_name,
        }

        # Moderators have 0 clubs by default
        club_count = 0

        access_token = create_access_token(data=token_data, club_count=club_count)
        refresh_token = create_refresh_token(token_data)
        expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60

        # Prepare user data
        user_data = {
            "user_id": str(user["_id"]),
            "full_name": full_name,
            "email": user_email,
            "phone": formatted_phone,
            "role": "moderator",
            "membership_status": "active",
            "membership_type": "free",
            "wants_membership": False,
            "terms_accepted": True,
            "terms_accepted_at": datetime.utcnow(),
            "subscription_id": None,
            "stripe_customer_id": None,
            "profile_picture": None,
            "email_verified": True,
            "is_profile_completed": True,
            "is_social_login": False,
            "social_logins": [],
            "created_at": user.get("created_at"),
            "updated_at": datetime.utcnow(),
            "last_login": datetime.utcnow(),
            "is_moderator": True,
            "moderator_status": "active",
        }

        return ProfileCompletionResponse(
            message="Moderator profile completed successfully",
            success=True,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=expires_in,
            user=user_data,
            # FCM token fields
            fcm_token=request.fcm_token if request.fcm_token else None,
            device_type=request.device_type if request.device_type else None,
            device_name=request.device_name if request.device_name else None,
            device_id=request.device_id if request.device_id else None,
        )

    except Exception as e:
        print(f"❌ Error completing moderator profile: {str(e)}")
        import traceback

        traceback.print_exc()
        return ProfileCompletionResponse(
            message=f"Failed to complete moderator profile: {str(e)}",
            success=False,
            access_token="",
            refresh_token="",
            token_type="bearer",
            expires_in=0,
            user={},
        )


# @router.get("/auth/profile-status/{user_id}")
# async def get_profile_status(user_id: str):
#     """
#     Check if user profile is completed
#     """
#     try:
#         status = await check_user_profile_status(user_id)
#         return {
#             "success": True,
#             "data": status,
#             "message": "Profile status retrieved successfully"
#         }
#     except HTTPException:
#         raise
#     except Exception as e:
#         return JSONResponse(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             content={
#                 "message": "Internal server error",
#                 "success": False,
#                 "error": str(e)
#             }
#         )

# @router.get("/auth/social-login-stats")
# async def get_social_login_stats():
#     """
#     Get statistics about social login usage (for admin purposes)
#     """
#     try:
#         # This would query the social_login_logs collection
#         # For now, return placeholder data
#         return {
#             "total_attempts": 0,
#             "successful_logins": 0,
#             "failed_logins": 0,
#             "providers": {
#                 "google": {"attempts": 0, "successes": 0, "failures": 0},
#                 "apple": {"attempts": 0, "successes": 0, "failures": 0},
#                 "facebook": {"attempts": 0, "successes": 0, "failures": 0}
#             },
#             "message": "Social login statistics"
#         }
#     except Exception as e:
#         return JSONResponse(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             content={
#                 "message": "Internal server error",
#                 "success": False,
#                 "error": str(e)
#             }
#         )
