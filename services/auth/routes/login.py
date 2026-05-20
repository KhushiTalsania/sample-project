from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from ..models import (
    SendOTPRequest,
    SendOTPResponse,
    VerifyOTPRequest,
    LoginResponse,
    ResendOTPRequest,
)
from ..utils import (
    generate_otp,
    send_sms_otp,
    store_otp,
    verify_stored_otp,
    create_access_token,
    create_refresh_token,
    get_user_by_phone,
    check_otp_resend_cooldown,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ACCESS_TOKEN_EXPIRE_MINUTES_REMEMBER,
    create_user_session,
)
from ..db import get_user_collection
from bson import ObjectId
from datetime import datetime
import os

router = APIRouter()


@router.post("/send-otp", response_model=SendOTPResponse)
async def send_otp(request: SendOTPRequest):
    """
    Send OTP to the provided phone number
    """
    try:
        # Format phone number - combine country code with phone number
        phone_number = request.phone_number.strip()
        country_code = request.country_code.strip()
        
        # Clean both values - remove any non-digit characters
        phone_number = ''.join(c for c in phone_number if c.isdigit())
        country_code = ''.join(c for c in country_code if c.isdigit())
        
        # Check if phone already contains country code
        if phone_number.startswith(country_code):
            # Phone already has country code, don't duplicate
            formatted_phone = phone_number
            print(f"🔍 Phone already contains country code, using as-is: {formatted_phone}")
        else:
            # Add country code to phone
            formatted_phone = f"{country_code}{phone_number}"
            print(f"🔍 Added country code to phone: {formatted_phone}")
        
        print(f"🔍 Phone formatting - Original: {request.phone_number}, Country Code: {request.country_code}")
        print(f"🔍 Cleaned phone: {phone_number}")
        print(f"🔍 Cleaned country code: {country_code}")
        print(f"🔍 Final formatted phone: {formatted_phone}")
        
        # Check if user exists
        user = await get_user_by_phone(formatted_phone)
        if not user:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "message": "User not found with this phone number",
                    "success": False,
                    "error": "user_not_found",
                },
            )

        # Check cooldown for resending OTP
        can_resend = await check_otp_resend_cooldown(formatted_phone)
        if not can_resend:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "message": "Please wait 1 minute before requesting another OTP",
                    "success": False,
                    "error": "rate_limited",
                },
            )

        # Generate OTP
        otp = generate_otp()
        print(f"🔢 Generated OTP: {otp}")

        # Store OTP in database
        stored = await store_otp(formatted_phone, otp)
        if not stored:
            print("❌ Failed to store OTP in database")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "message": "Failed to store OTP",
                    "success": False,
                    "error": "storage_error",
                },
            )
        print("✅ OTP stored in database successfully")

        # Send OTP via SMS
        sms_sent = await send_sms_otp(formatted_phone, otp)
        if not sms_sent:
            print("❌ Failed to send OTP via SMS")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "message": "Failed to send OTP via SMS",
                    "success": False,
                    "error": "sms_error",
                },
            )

        return {"message": "OTP sent successfully", "success": True}

    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Internal server error",
                "success": False,
                "error": str(e),
            },
        )


@router.post("/verify-otp", response_model=LoginResponse)
async def verify_otp(request: VerifyOTPRequest):
    """
    Verify OTP and login user
    """
    try:
        # Format phone number - combine country code with phone number
        phone_number = request.phone_number.strip()
        country_code = request.country_code.strip()
        
        # Clean both values - remove any non-digit characters
        phone_number = ''.join(c for c in phone_number if c.isdigit())
        country_code = ''.join(c for c in country_code if c.isdigit())
        
        # Check if phone already contains country code
        if phone_number.startswith(country_code):
            # Phone already has country code, don't duplicate
            formatted_phone = phone_number
            print(f"🔍 Phone already contains country code, using as-is: {formatted_phone}")
        else:
            # Add country code to phone
            formatted_phone = f"{country_code}{phone_number}"
            print(f"🔍 Added country code to phone: {formatted_phone}")
        
        print(f"🔍 Phone formatting - Original: {request.phone_number}, Country Code: {request.country_code}")
        print(f"🔍 Final formatted phone: {formatted_phone}")
        
        # Get user by phone number
        user = await get_user_by_phone(formatted_phone)
        if not user:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "message": "User not found",
                    "access_token": "",
                    "error": "user_not_found",
                },
            )

        # Verify OTP
        print(f"🔍 Verifying OTP: {request.otp} for phone: {formatted_phone}")
        otp_valid = await verify_stored_otp(formatted_phone, request.otp)
        if not otp_valid:
            print("❌ OTP verification failed")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "message": "Invalid or expired OTP",
                    "access_token": "",
                    "error": "invalid_otp",
                },
            )
        print("✅ OTP verification successful")

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
                    f"❌ Login blocked - User {request.phone_number} is temporarily deactivated"
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
                    f"❌ Login blocked - User {request.phone_number} has been temporarily deleted by admin"
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
                f"❌ Login blocked - User {request.phone_number} has been permanently deleted by admin"
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

        # Block login for inactive users ONLY if deleted by admin (temp or permanent)
        if user_status == "inactive" and (
            is_deleted_temp_admin or is_deleted_per_admin
        ):
            print(
                f"❌ Login blocked - User {request.phone_number} is inactive due to admin deletion"
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "message": "Access denied. Your account is inactive due to admin action. Please contact support.",
                    "access_token": "",
                    "error": "account_inactive_admin",
                    "user_status": user_status,
                    "is_deleted_temp_admin": is_deleted_temp_admin,
                    "is_deleted_per_admin": is_deleted_per_admin,
                },
            )

        # Block login for deleted users
        if user_status == "deleted" or membership_status == "deleted":
            print(
                f"❌ Login blocked - User {request.phone_number} has been permanently deleted"
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
            # If also inactive due to admin deletion, unify response with inactive-admin handling
            is_deleted_per_admin = user.get("is_deleted_per_admin", False)
            if user_status == "inactive" and (
                is_deleted_temp_admin or is_deleted_per_admin
            ):
                print(
                    f"❌ Login blocked - User {request.phone_number} is inactive due to admin deletion (permanent deactivate)"
                )
                # Convert datetime to ISO format string if it exists
                deactivated_at = user.get("deactivated_at")
                if deactivated_at and hasattr(deactivated_at, "isoformat"):
                    deactivated_at = deactivated_at.isoformat()
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "message": "Access denied. Your account is inactive due to admin action. Please contact support.",
                        "access_token": "",
                        "error": "account_inactive_admin",
                        "user_status": user_status,
                        "is_deleted_temp_admin": is_deleted_temp_admin,
                        "is_deleted_per_admin": is_deleted_per_admin,
                        "deactivated_at": deactivated_at,
                        "deactivated_by": user.get("deactivated_by"),
                        "deactivation_reason": user.get("deactivation_reason"),
                    },
                )
            print(
                f"❌ Login blocked - User {request.phone_number} is temporarily deactivated"
            )
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
                f"❌ Login blocked - User {request.phone_number} has been temporarily deleted by admin"
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
            "user_id": str(user["_id"]),
            "full_name": user["full_name"],
            "email": user["email"],
            "phone": user["phone"],
            "role": user["role"],
            "membership_status": user.get("membership_status", "inactive"),
            "wants_membership": user.get("wants_membership", False),
            "terms_accepted": user.get("terms_accepted", False),
            "terms_accepted_at": user.get("terms_accepted_at"),
            "subscription_id": user.get("subscription_id"),
            "stripe_customer_id": user.get("stripe_customer_id"),
            "complete_step": user.get("complete_step", 0),
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
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
        try:
            from ..utils import create_user_session

            session_id = await create_user_session(
                str(user["_id"]), access_token, "Phone OTP Login"
            )
            print(f"✅ Session created for phone OTP login user: {user['_id']}")
        except Exception as session_error:
            print(
                f"⚠️ Failed to create session for phone OTP login user: {str(session_error)}"
            )
            # Don't fail the login if session creation fails

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

        response_data = {
            "message": "Login successful",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": user_data,
        }
        print(
            f"✅ Login successful - Response prepared with refresh_token: {refresh_token is not None}"
        )
        return response_data

    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Internal server error",
                "access_token": "",
                "error": str(e),
            },
        )


@router.post("/resend-otp", response_model=SendOTPResponse)
async def resend_otp(request: ResendOTPRequest):
    """
    Resend OTP to the provided phone number
    """
    try:
        # Format phone number - combine country code with phone number
        phone_number = request.phone_number.strip()
        country_code = request.country_code.strip()
        
        # Clean both values - remove any non-digit characters
        phone_number = ''.join(c for c in phone_number if c.isdigit())
        country_code = ''.join(c for c in country_code if c.isdigit())
        
        # Check if phone already contains country code
        if phone_number.startswith(country_code):
            # Phone already has country code, don't duplicate
            formatted_phone = phone_number
            print(f"🔍 Phone already contains country code, using as-is: {formatted_phone}")
        else:
            # Add country code to phone
            formatted_phone = f"{country_code}{phone_number}"
            print(f"🔍 Added country code to phone: {formatted_phone}")
        
        print(f"🔍 Phone formatting - Original: {request.phone_number}, Country Code: {request.country_code}")
        print(f"🔍 Cleaned phone: {phone_number}")
        print(f"🔍 Cleaned country code: {country_code}")
        print(f"🔍 Final formatted phone: {formatted_phone}")
        
        # Check if user exists
        user = await get_user_by_phone(formatted_phone)
        if not user:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "message": "User not found with this phone number",
                    "success": False,
                    "error": "user_not_found",
                },
            )

        # Check cooldown for resending OTP
        can_resend = await check_otp_resend_cooldown(formatted_phone)
        if not can_resend:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "message": "Please wait 1 minute before requesting another OTP",
                    "success": False,
                    "error": "rate_limited",
                },
            )

        # Generate new OTP
        otp = generate_otp()
        print(f"🔢 Generated new OTP for resend: {otp}")

        # Store new OTP in database
        stored = await store_otp(formatted_phone, otp)
        if not stored:
            print("❌ Failed to store new OTP in database")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "message": "Failed to store OTP",
                    "success": False,
                    "error": "storage_error",
                },
            )
        print("✅ New OTP stored in database successfully")

        # Send new OTP via SMS
        sms_sent = await send_sms_otp(formatted_phone, otp)
        if not sms_sent:
            print("❌ Failed to send new OTP via SMS")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "message": "Failed to send OTP via SMS",
                    "success": False,
                    "error": "sms_error",
                },
            )

        return {"message": "OTP resent successfully", "success": True}

    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Internal server error",
                "success": False,
                "error": str(e),
            },
        )
