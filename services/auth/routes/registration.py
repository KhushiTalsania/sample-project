from fastapi import APIRouter, HTTPException, Depends
from ..models import UserRegistrationRequest, UserRegistrationResponse, AccountStatus, ProfileCompletionRequest, ProfileCompletionResponse, UserCompletionStatusResponse
from ..db import get_user_collection
from ..utils import hash_password, create_access_token, create_refresh_token, ACCESS_TOKEN_EXPIRE_MINUTES, verify_token, get_current_user
from motor.motor_asyncio import AsyncIOMotorCollection
from fastapi.responses import JSONResponse
from datetime import datetime
from bson import ObjectId
import os

router = APIRouter()

@router.post("/register", response_model=UserRegistrationResponse)
async def register_user(user: UserRegistrationRequest):
    users: AsyncIOMotorCollection = get_user_collection()
    
    # Check if email or phone already exists
    if await users.find_one({"email": user.email}):
        return JSONResponse(status_code=400, content={"message": "Email already registered", "error": "email_exists"})
    if await users.find_one({"phone": user.phone}):
        return JSONResponse(status_code=404, content={"message": "Phone number is already registered.", "error": "phone_exists"})
    
    # Hash password
    hashed_pw = hash_password(user.password)
    
    # Create user document with membership fields
    user_doc = {
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "password_hash": hashed_pw,
        "role": user.role,
        # Default account status -> active at registration
        "status": AccountStatus.ACTIVE.value,
        "wants_membership": True,
        "terms_accepted": user.terms_accepted,
        "terms_accepted_at": datetime.utcnow() if user.terms_accepted else None,
        "membership_status": "inactive",  # "inactive", "pending", "active", "cancelled"
        "subscription_id": None,
        "stripe_customer_id": None,
        "complete_step": 0,  # User just visited, step 0
        "club_count": 0,  # Initialize club_count to 0 for both captains and members
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = await users.insert_one(user_doc)
    user_id = str(result.inserted_id)
    
    # Generate JWT tokens for automatic login after registration
    # For new users, club count will be 0 for both captains and members
    club_count = 0
    if user.role == "Captain":
        print(f"👑 New Captain registered - initial club count: {club_count}")
    elif user.role == "Member":
        print(f"👤 New Member registered - initial club count: {club_count}")
    
    access_token = create_access_token(
        data={"sub": user_id, "user_id": user_id, "full_name": user.full_name, "role": user.role}, 
        club_count=club_count
    )
    refresh_token = create_refresh_token(data={"sub": user_id, "user_id": user_id, "full_name": user.full_name})
    
    # Create user session for the generated access token
    try:
        from ..utils import create_user_session
        await create_user_session(user_id, access_token, "Registration")
        print(f"✅ Session created for newly registered user: {user_id}")
    except Exception as session_error:
        print(f"⚠️ Failed to create session for new user: {str(session_error)}")
        # Don't fail registration if session creation fails
    
    # Create safe user object (exclude password_hash for security)
    safe_user_info = {
        "user_id": user_id,
        "full_name": user_doc["full_name"],
        "email": user_doc["email"],
        "phone": user_doc["phone"],
        "role": user_doc["role"],
        "membership_status": user_doc["membership_status"],
        "status": user_doc["status"],
        "wants_membership": user_doc["wants_membership"],
        "terms_accepted": user_doc["terms_accepted"],
        "terms_accepted_at": user_doc["terms_accepted_at"],
        "subscription_id": user_doc["subscription_id"],
        "stripe_customer_id": user_doc["stripe_customer_id"],
        "created_at": user_doc["created_at"],
        "updated_at": user_doc["updated_at"],
        "complete_step": user_doc["complete_step"]
    }
    
    # Initialize Stripe Connect variables
    stripe_connect_account_id = None
    stripe_onboarding_url = None
    stripe_connect_status = None
    
    # For Captain role, create Stripe Connect account
    if user.role == "Captain":
        try:
            # Import Stripe Connect service
            from services.club.stripe_connect_service import StripeConnectService
            
            stripe_connect_service = StripeConnectService()
            
            # Create Stripe Connect account for the Captain
            print(f"🚀 Creating Stripe Connect account for Captain: {user.email}")
            
            connect_result = await stripe_connect_service.create_captain_connect_account(
                captain_id=user_id,
                captain_email=user.email,
                captain_name=user.full_name,
                country='US'  # Default country, can be made configurable
            )
            
            if connect_result.get("success"):
                stripe_connect_account_id = connect_result.get("account_id")
                stripe_onboarding_url = connect_result.get("onboarding_url")
                stripe_connect_status = connect_result.get("status", "pending_onboarding")
                
                print(f"✅ Stripe Connect account created for Captain {user_id}")
                print(f"   Account ID: {stripe_connect_account_id}")
                print(f"   Onboarding URL: {stripe_onboarding_url}")
                
                # Update safe_user_info with Stripe Connect details
                safe_user_info["stripe_connect_account_id"] = stripe_connect_account_id
                safe_user_info["stripe_connect_status"] = stripe_connect_status
            else:
                print(f"⚠️ Failed to create Stripe Connect account: {connect_result.get('error')}")
                # Don't fail registration if Stripe Connect setup fails
                
        except Exception as stripe_error:
            print(f"⚠️ Error creating Stripe Connect account for Captain: {str(stripe_error)}")
            # Don't fail registration if Stripe Connect setup fails
    
    return UserRegistrationResponse(
        message="Registration successful" if user.role != "Captain" else "Registration successful. Please complete Stripe onboarding to start receiving payments.",
        user_id=user_id,
        requires_membership=user.wants_membership,
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert minutes to seconds
        membership_status=user_doc["membership_status"],
        wants_membership=user.wants_membership,
        status=user_doc["status"],
        user=safe_user_info,
        # Stripe Connect fields (will be None for Members)
        stripe_connect_account_id=stripe_connect_account_id,
        stripe_onboarding_url=stripe_onboarding_url,
        stripe_connect_status=stripe_connect_status
    )

@router.post("/complete-profile", response_model=ProfileCompletionResponse)
async def complete_profile_after_subscription(request: ProfileCompletionRequest):
    """
    Complete user profile after successful subscription creation.
    This endpoint is called after the user completes payment and wants to finish their profile.
    """
    try:
        # Find user by email
        users_collection = get_user_collection()
        
        user = await users_collection.find_one({
            "email": request.email.lower()
        })
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found with provided email. Please complete subscription first."
            )
        
        # Get verify_token from database for validation
        db_verify_token = user.get("verify_token")
        if not db_verify_token:
            raise HTTPException(
                status_code=400,
                detail="No verify token found for user. Please complete subscription first."
            )
        
        # Validate verify_token from database
        try:
            token_payload = verify_token(db_verify_token)
            if not token_payload:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired verify_token"
                )
            
            # Validate token email matches request email
            token_email = token_payload.get('email')
            if token_email != request.email.lower():
                raise HTTPException(
                    status_code=401,
                    detail="Token email does not match request email"
                )
            
            # Validate token purpose
            token_purpose = token_payload.get('purpose')
            if token_purpose != 'verification':
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token purpose"
                )
            
            print(f"✅ Verify token from database validated for email: {request.email}")
            
        except Exception as e:
            print(f"❌ Token validation error: {str(e)}")
            raise HTTPException(
                status_code=401,
                detail=f"Token validation failed: {str(e)}"
            )
        
        # Check if user has active membership
        if user.get("membership_status") != "active":
            raise HTTPException(
                status_code=400,
                detail="User does not have active membership. Please complete subscription first."
            )
        
        # Check if profile is already completed
        if user.get("profile_completed", False):
            raise HTTPException(
                status_code=400,
                detail="User profile is already completed"
            )
        
        # Update user profile
        full_name = f"{request.first_name} {request.last_name}".strip()
        hashed_password = hash_password(request.password)
        
        # Get role from request if provided, otherwise use existing user role or default to "Member"
        user_role = request.role if request.role else user.get("role", "Member")


        # Combine country code with phone number
        formatted_phone = f"{request.country_code}{request.phone}"
        # Format phone number - prevent duplicate country code
        phone_number = request.phone.strip()
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
        
        print(f"🔍 Phone formatting - Original: {request.phone}, Country Code: {request.country_code}")
        print(f"🔍 Cleaned phone: {phone_number}")
        print(f"🔍 Cleaned country code: {country_code}")
        print(f"🔍 Final formatted phone: {formatted_phone}")
        
        # Validate final phone number length (7-15 characters)
        if len(formatted_phone) < 7 or len(formatted_phone) > 15:
            raise HTTPException(
                status_code=400,
                detail="Phone number must be between 7 and 15 characters long"
            )
        
        # Check if phone number is already taken by another user
        existing_user_with_phone = await users_collection.find_one({
            "phone": formatted_phone,
            "_id": {"$ne": user["_id"]}  # Exclude current user
        })
        
        if existing_user_with_phone:
            raise HTTPException(
                status_code=404,
                detail="Phone number is already registered."
            )
        
        update_result = await users_collection.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "full_name": full_name,
                    "first_name": request.first_name,
                    "last_name": request.last_name,
                    "phone": formatted_phone,
                    "country_code": request.country_code,
                    "password_hash": hashed_password,
                    "role": user_role or "Member",
                    "profile_completed": True,
                    "profile_completed_at": datetime.utcnow(),
                    "complete_step": 1,  # Profile completed, step 1 (not 2)
                    "updated_at": datetime.utcnow(),
                    "is_auto_created": False  # Mark as manually completed
                },
                "$unset": {
                    "temp_password": "",
                    "temp_password_created_at": ""
                }
            }
        )
        
        if update_result.modified_count == 0:
            raise HTTPException(
                status_code=500,
                detail="Failed to update user profile"
            )
        
        print(f"✅ User profile completed for: {request.email}")
        
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
                        <h2 style="color: #4CAF50; margin-top: 0;">Welcome to MVP Sports, {request.first_name}!</h2>
                        
                        <p>Your profile has been completed successfully. Here are your account details:</p>
                        
                        <div style="background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4CAF50;">
                            <h3 style="margin-top: 0; color: #4CAF50;">Account Information</h3>
                            <p><strong>Full Name:</strong> {full_name}</p>
                            <p><strong>Email:</strong> {request.email}</p>
                            <p><strong>Phone:</strong> {formatted_phone}</p>
                            <p><strong>Role:</strong> {user_role or "Member"}</p>
                            <p><strong>Membership Status:</strong> {user.get("membership_status", "Active")}</p>
                            <p><strong>Membership Type:</strong> {user.get("membership_type", "Trial")}</p>
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
                            <p style="margin-bottom: 0;">Please keep your login credentials secure and never share them with anyone. If you need to reset your password, you can do so from your account settings.</p>
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
                to_email=request.email,
                subject=email_subject,
                html_content=email_body
            )
            print(f"✅ Profile completion email sent to: {request.email}")
            
        except Exception as email_error:
            print(f"⚠️ Failed to send profile completion email: {str(email_error)}")
            # Don't fail the profile completion if email fails
        
        # Generate new access token for the updated user
        token_data = {
            "sub": str(user["_id"]),
            "email": request.email.lower(),
            "full_name": full_name,
            "role": user_role or "Member",  # Ensure we always have a valid role
        }
        
        # Get club count for both captains and members
        club_count = 0
        if user_role == "Captain":
            try:
                from ..utils import get_club_count_for_captain, update_user_club_count
                club_count = await get_club_count_for_captain(str(user["_id"]))
                # Update the user's club count in the database
                await update_user_club_count(str(user["_id"]), club_count)
                print(f"👑 Captain {full_name} has {club_count} clubs (complete-profile)")
            except Exception as e:
                print(f"⚠️ Could not get club count for captain during complete-profile: {e}")
                # Use stored club count if available
                club_count = user.get("club_count", 0)
        elif user_role == "Member":
            try:
                from ..utils import get_club_count_for_member, update_user_club_count
                club_count = await get_club_count_for_member(str(user["_id"]))
                # Update the user's club count in the database
                await update_user_club_count(str(user["_id"]), club_count)
                print(f"👤 Member {full_name} has {club_count} clubs (complete-profile)")
            except Exception as e:
                print(f"⚠️ Could not get club count for member during complete-profile: {e}")
                # Use stored club count if available
                club_count = user.get("club_count", 0)
        
        access_token = create_access_token(data=token_data, club_count=club_count)
        refresh_token = create_refresh_token(data=token_data)
        
        # Create user session for the new access token
        try:
            from ..utils import create_user_session
            await create_user_session(str(user["_id"]), access_token, "Profile Completion")
            print(f"✅ Session created for profile completion: {str(user['_id'])}")
        except Exception as session_error:
            print(f"⚠️ Failed to create session for profile completion: {str(session_error)}")
            # Don't fail profile completion if session creation fails
        
        # Store both access_token and refresh_token in database
        await users_collection.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "token_created_at": datetime.utcnow()
                }
            }
        )
        
        # Initialize Stripe Connect variables
        stripe_connect_account_id = None
        stripe_onboarding_url = None
        stripe_connect_status = None
        
        # For Captain role, create Stripe Connect account
        if user_role == "Captain":
            try:
                # Import Stripe Connect service
                from services.club.stripe_connect_service import StripeConnectService
                
                stripe_connect_service = StripeConnectService()
                
                # Create Stripe Connect account for the Captain
                print(f"🚀 Creating Stripe Connect account for Captain (Profile Completion): {request.email}")
                
                connect_result = await stripe_connect_service.create_captain_connect_account(
                    captain_id=str(user["_id"]),
                    captain_email=request.email.lower(),
                    captain_name=full_name,
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
        
        # Prepare user data with Stripe Connect info if Captain
        user_data = {
            "user_id": str(user["_id"]),
            "email": request.email.lower(),
            "first_name": request.first_name,
            "last_name": request.last_name,
            "full_name": full_name,
            "phone": formatted_phone,
            "country_code": request.country_code,
            "role": user_role or "Member",
            "membership_status": user.get("membership_status"),
            "membership_type": user.get("membership_type"),
            "profile_completed": True,
            "complete_step": 1,  # Profile completed, step 1 (not 2)
            "subscription_id": user.get("subscription_id"),
            "stripe_customer_id": user.get("stripe_customer_id")
        }
        
        # Add Stripe Connect info to user data if Captain
        if stripe_connect_account_id:
            user_data["stripe_connect_account_id"] = stripe_connect_account_id
            user_data["stripe_connect_status"] = stripe_connect_status
        
        # Register FCM device token if provided
        if request.fcm_token:
            try:
                from services.notifications.notification_service import register_device_token
                
                # Set default device type if not provided
                device_type = request.device_type or "unknown"
                device_name = request.device_name or "Unknown Device"
                device_id = request.device_id or None
                
                token_result = await register_device_token(
                    user_id=str(user["_id"]),
                    device_token=request.fcm_token,
                    device_type=device_type,
                    device_name=device_name,
                    device_id=device_id
                )
                
                if token_result.get("success"):
                    print(f"✅ FCM token registered for user {str(user['_id'])}: {token_result.get('message')}")
                else:
                    print(f"⚠️ Failed to register FCM token: {token_result.get('error')}")
            except Exception as token_error:
                print(f"⚠️ Error registering FCM token: {str(token_error)}")
                # Don't fail profile completion if token registration fails
        
        return ProfileCompletionResponse(
            success=True,
            message="Profile completed successfully" if user_role != "Captain" else "Profile completed successfully. Please complete Stripe onboarding to start receiving payments.",
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=user_data,
            # Stripe Connect fields (will be None for Members)
            stripe_connect_account_id=stripe_connect_account_id,
            stripe_onboarding_url=stripe_onboarding_url,
            stripe_connect_status=stripe_connect_status
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error completing profile: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error completing profile: {str(e)}"
        )

@router.get("/completion-status", response_model=UserCompletionStatusResponse)
async def get_user_completion_status(current_user: dict = Depends(get_current_user)):
    """
    Get current user's completion status and progress
    """
    try:
        users_collection = get_user_collection()
        user_id = current_user["user_id"]
        
        # Find user by ID
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )
        
        # Debug: Log the user document to see what fields are present
        print(f"🔍 User document for {user_id}:")
        print(f"🔍 - complete_step: {user.get('complete_step')}")
        print(f"🔍 - membership_status: {user.get('membership_status')}")
        print(f"🔍 - profile_completed: {user.get('profile_completed')}")
        print(f"🔍 - is_profile_completed: {user.get('is_profile_completed')}")
        print(f"🔍 - is_social_login: {user.get('is_social_login')}")
        print(f"🔍 - role: {user.get('role')}")
        
                # Check if user has complete_step field, if not, determine and set it
        if "complete_step" not in user:
            print(f"⚠️ User {user_id} missing complete_step field, auto-fixing...")
            
            # Determine appropriate complete_step based on user's current state
            complete_step = 0
            
            # If user has active membership, they've completed payment (step 1)
            if user.get("membership_status") == "active":
                complete_step = 1
                
                # If user has completed profile or is social login, they're at step 1 (not 2)
                # Profile completion and social login keep users at step 1 until they join a club
                profile_completed_check = user.get("profile_completed", False) or user.get("is_profile_completed", False)
                if profile_completed_check:
                    complete_step = 1  # Profile completed but still at step 1
                    
            # Special handling for social login users - they stay at step 1 after payment
            if user.get("is_social_login", False) and user.get("membership_status") == "active":
                complete_step = 1  # Social login users with active membership stay at step 1
                print(f"🔍 Auto-fixing social login user {user_id} - setting complete_step to 1")
                    
            print(f"🔍 Auto-fixing user {user_id}: membership_status={user.get('membership_status')}, profile_completed={user.get('profile_completed')}, is_profile_completed={user.get('is_profile_completed')}, profile_completed_check={profile_completed_check}, calculated_step={complete_step}")
            
            # Update the user's complete_step field
            try:
                await users_collection.update_one(
                    {"_id": ObjectId(user_id)},
                    {
                        "$set": {
                            "complete_step": complete_step,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                print(f"✅ Auto-fixed user {user_id} complete_step to {complete_step}")
            except Exception as fix_error:
                print(f"❌ Error auto-fixing user complete_step: {str(fix_error)}")
        else:
            complete_step = user.get("complete_step", 0)
            
            # Validate that complete_step is logically consistent with user's current state
            expected_step = 0
            if user.get("membership_status") == "active":
                expected_step = 1
                # Check both field names for compatibility
                profile_completed_check = user.get("profile_completed", False) or user.get("is_profile_completed", False)
                if profile_completed_check:
                    expected_step = 1  # Profile completed but still at step 1
                    
            # Special handling for social login users - they stay at step 1 after payment
            if user.get("is_social_login", False) and user.get("membership_status") == "active":
                expected_step = 1  # Social login users with active membership stay at step 1
                print(f"🔍 Social login user {user_id} - setting expected_step to 1")
                    
            print(f"🔍 User {user_id} validation: current_step={complete_step}, expected_step={expected_step}, membership_status={user.get('membership_status')}, profile_completed={user.get('profile_completed')}, is_profile_completed={user.get('is_profile_completed')}, profile_completed_check={profile_completed_check}")
            
            if complete_step != expected_step:
                print(f"⚠️ User {user_id} complete_step ({complete_step}) inconsistent with state, correcting to {expected_step}")
                try:
                    await users_collection.update_one(
                        {"_id": ObjectId(user_id)},
                        {
                            "$set": {
                                "complete_step": expected_step,
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    complete_step = expected_step
                    print(f"✅ Corrected user {user_id} complete_step to {expected_step}")
                except Exception as correct_error:
                    print(f"❌ Error correcting user complete_step: {str(correct_error)}")
        
        # Define all steps
        all_steps = [
            "Visit site",
            "Complete payment/Profile",  # Combined step 1: payment + profile completion
            "Join club"  # Step 2: joining a club
        ]
        
        # Get completed and remaining steps
        # complete_step represents the CURRENT step the user is on
        # complete_step = 0: User just visited (step 0)
        # complete_step = 1: User completed payment and profile (step 1) 
        # complete_step = 2: User joined a club (step 2)
        steps_completed = all_steps[:complete_step + 1]  # Include the current step as completed
        steps_remaining = all_steps[complete_step + 1:]  # Remaining steps start after the current step
        
        # For debugging, let's log what we're calculating
        print(f"🔍 User {user_id} complete_step: {complete_step}")
        print(f"🔍 All steps: {all_steps}")
        print(f"🔍 Steps completed: {steps_completed}")
        print(f"🔍 Steps remaining: {steps_remaining}")
        
        # Verify the logic is correct
        if complete_step == 0:
            expected_completed = ["Visit site"]
            expected_remaining = ["Complete payment/Profile", "Join club"]
            print(f"🔍 Expected for complete_step=0: completed={expected_completed}, remaining={expected_remaining}")
            print(f"🔍 Actual: completed={steps_completed}, remaining={steps_remaining}")
        elif complete_step == 1:
            expected_completed = ["Visit site", "Complete payment/Profile"]
            expected_remaining = ["Join club"]
            print(f"🔍 Expected for complete_step=1: completed={expected_completed}, remaining={expected_remaining}")
            print(f"🔍 Actual: completed={steps_completed}, remaining={steps_remaining}")
        elif complete_step == 2:
            expected_completed = ["Visit site", "Complete payment/Profile", "Join club"]
            expected_remaining = []
            print(f"🔍 Expected for complete_step=2: completed={expected_completed}, remaining={expected_remaining}")
            print(f"🔍 Actual: completed={steps_completed}, remaining={steps_remaining}")
        
        # Calculate progress percentage
        # Since complete_step represents the current step (0-based), we need to add 1 to get the actual number of completed steps
        # Now with 3 steps: 0=Visit, 1=Payment/Profile, 2=Join Club
        actual_completed_steps = complete_step + 1
        progress_percentage = (actual_completed_steps / len(all_steps)) * 100
        
        # Determine next step
        # Since complete_step represents the current step, the next step is at complete_step + 1
        # Now with 3 steps: 0=Visit, 1=Payment/Profile, 2=Join Club
        if complete_step >= len(all_steps) - 1:  # If user is at or beyond the last step
            next_step = "All steps completed!"
        else:
            next_step = all_steps[complete_step + 1]  # Next step is the one after current
        
        # Create safe user object (exclude sensitive data)
        # Check both profile completion field names for compatibility
        profile_completed = user.get("profile_completed", False) or user.get("is_profile_completed", False)
        
        # Special handling for social login users - they should always have profile_completed = true
        if user.get("is_social_login", False) and user.get("membership_status") == "active":
            profile_completed = True
            print(f"🔍 Social login user {user_id} - forcing profile_completed to True")
        
        safe_user_info = {
            "user_id": str(user["_id"]),
            "email": user.get("email"),
            "full_name": user.get("full_name"),
            "role": user.get("role"),
            "membership_status": user.get("membership_status"),
            "membership_type": user.get("membership_type"),
            "profile_completed": profile_completed,
            "complete_step": complete_step
        }
        
        # Final debug logging before response
        print(f"🔍 Final response for user {user_id}:")
        print(f"🔍 - complete_step: {complete_step}")
        print(f"🔍 - steps_completed: {steps_completed}")
        print(f"🔍 - steps_remaining: {steps_remaining}")
        print(f"🔍 - profile_completed: {profile_completed}")
        print(f"🔍 - safe_user_info: {safe_user_info}")
        
        return UserCompletionStatusResponse(
            message=f"User has completed {actual_completed_steps} out of {len(all_steps)} steps",
            user_id=str(user["_id"]),
            complete_step=complete_step,
            steps_completed=steps_completed,
            steps_remaining=steps_remaining,
            progress_percentage=progress_percentage,
            next_step=next_step,
            user=safe_user_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error getting user completion status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting user completion status: {str(e)}"
        ) 