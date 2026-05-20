from passlib.context import CryptContext
import random
import time
from typing import Optional
import jwt
from datetime import datetime, timedelta, timezone
import re
import os
from .db import (
    get_user_collection, db, get_session_blacklist_collection,
    get_active_sessions_collection, get_session_activity_collection
)
from twilio.rest import Client
import secrets
import uuid
import hashlib
from core.utils.email_service import send_email as send_email_centralized
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId
import requests
import base64
import httpx
from jose import jwt
from jose.exceptions import JWTError
from dotenv import load_dotenv
load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Configuration
SECRET_KEY = os.getenv('JWT_SECRET', 'your_super_secret_jwt_key')
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
ACCESS_TOKEN_EXPIRE_MINUTES_REMEMBER = 60 * 24 * 30  # 30 days

# Email Configuration - Now using centralized email service from core.utils.email_service

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID',"")
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN',"")
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER',"")

# OTP Configuration
OTP_EXPIRY_MINUTES = 5
OTP_RESEND_COOLDOWN_SECONDS = 60

# Password Reset Configuration
PASSWORD_RESET_TOKEN_EXPIRY_MINUTES = 30
APP_BASE_URL = os.getenv('simbet_website_url', 'http://localhost:3000')

# Session Management Configuration
SESSION_INACTIVITY_TIMEOUT_MINUTES = 30  # 30 minutes of inactivity
SESSION_CLEANUP_INTERVAL_MINUTES = 15    # Clean expired sessions every 15 minutes
MAX_SESSIONS_PER_USER = 5                # Maximum concurrent sessions per user

# Social Login Configuration
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '656955237369-hutssoab8gd0drle4bi569qr44f07kqs.apps.googleusercontent.com')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', 'your_google_client_secret')
APPLE_CLIENT_ID = os.getenv('APPLE_CLIENT_ID', 'your_apple_client_id')
APPLE_TEAM_ID = os.getenv('APPLE_TEAM_ID', 'your_apple_team_id')
APPLE_KEY_ID = os.getenv('APPLE_KEY_ID', 'your_apple_key_id')
APPLE_PRIVATE_KEY = os.getenv('APPLE_PRIVATE_KEY', 'your_apple_private_key')
# FACEBOOK_APP_ID = os.getenv('FACEBOOK_APP_ID', 'your_facebook_app_id')
# FACEBOOK_APP_SECRET = os.getenv('FACEBOOK_APP_SECRET', 'your_facebook_app_secret')

# Initialize Twilio client
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    print("✅ Twilio client initialized successfully")
else:
    print("⚠️  Twilio credentials not found - SMS functionality will not work")

# Security scheme for JWT authentication
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Get current user from JWT token with enhanced session management"""
    token = credentials.credentials
    
    # Check if token is blacklisted
    if await is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify token
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user from database
    users_collection = get_user_collection()
    
    # Get user_id from payload - auth service uses 'sub' as the key
    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user ID",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check session timeout and create session if needed
    session_expired = await check_session_timeout(user_id, token)
    if session_expired:
        # Try to create a new session if the token is valid but no session exists
        try:
            await create_user_session(user_id, token, "Auto-created")
            print(f"✅ Auto-created session for user {user_id}")
            session_expired = False
        except Exception as session_error:
            print(f"⚠️ Failed to auto-create session: {str(session_error)}")
            # If we can't create a session, we'll still allow the request to proceed
            # but log the issue for debugging
    
    if session_expired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired due to inactivity",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
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
    
    # Update session activity (this will also create a session if it doesn't exist)
    try:
        await update_session_activity(user_id, token=token)
    except Exception as activity_error:
        print(f"⚠️ Failed to update session activity: {str(activity_error)}")
        # Don't fail the request if session activity update fails
    
    return {
        "user_id": str(user["_id"]),
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"],
        "avatar_url": user.get("avatar_url")
    }

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def generate_otp() -> str:
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None, remember_me: bool = False, club_count: int = 0) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    # Add club_count to the token payload for both captains and members
    user_role = data.get("role")
    if user_role in ["Captain", "Member"]:
        to_encode["club_count"] = club_count
        if user_role == "Captain":
            print(f"👑 Adding club count {club_count} to JWT token for Captain")
        else:
            print(f"👤 Adding club count {club_count} to JWT token for Member")
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        if remember_me:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES_REMEMBER)
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token for remember me functionality"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=30)  # 30 days
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.JWTError:
        return None

async def send_sms_otp(phone_number: str, otp: str) -> bool:
    """Send OTP via Twilio SMS"""
    print(phone_number,"phone_numberphone_numberphone_numberphone_number")
    print(TWILIO_ACCOUNT_SID,TWILIO_PHONE_NUMBER,TWILIO_AUTH_TOKEN)
    if not twilio_client:
        print(twilio_client,"twilio_clienttwilio_clienttwilio_clienttwilio_client")
        print("❌ Twilio client not configured")
        return False
    
    try:
        # Format phone number for Twilio (ensure it starts with +)
        formatted_phone = phone_number if phone_number.startswith('+') else f"+{phone_number}"
        
        print(f"📱 Sending OTP to: {formatted_phone}")
        print(f"🔑 OTP: {otp}")
        
        message = twilio_client.messages.create(
            body=f"Your OTP for login is: {otp}. Valid for {OTP_EXPIRY_MINUTES} minutes.",
            from_=TWILIO_PHONE_NUMBER,
            to=formatted_phone
        )
        
        print(f"✅ OTP sent successfully!")
        print(f"📨 Message SID: {message.sid}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send OTP.")
        print(f"🔍 Error: {e}")
        return False

async def store_otp(phone_number: str, otp: str) -> bool:
    """Store OTP in database with expiry"""
    try:
        otp_collection = db['otps']
        expiry_time = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)
        
        # Remove any existing OTP for this phone number
        await otp_collection.delete_many({"phone_number": phone_number})
        
        # Store new OTP
        otp_doc = {
            "phone_number": phone_number,
            "otp": otp,
            "expires_at": expiry_time,
            "used": False,
            "created_at": datetime.utcnow()
        }
        await otp_collection.insert_one(otp_doc)
        return True
    except Exception as e:
        print(f"Error storing OTP: {e}")
        return False

async def verify_stored_otp(phone_number: str, otp: str) -> bool:
    """Verify OTP from database"""
    try:
        otp_collection = db['otps']
        otp_doc = await otp_collection.find_one({
            "phone_number": phone_number,
            "otp": otp,
            "used": False,
            "expires_at": {"$gt": datetime.utcnow()}
        })
        
        if otp_doc:
            # Mark OTP as used
            await otp_collection.update_one(
                {"_id": otp_doc["_id"]},
                {"$set": {"used": True}}
            )
            return True
        return False
    except Exception as e:
        print(f"Error verifying OTP: {e}")
        return False

async def check_otp_resend_cooldown(phone_number: str) -> bool:
    """Check if enough time has passed since last OTP request"""
    try:
        otp_collection = db['otps']
        last_otp = await otp_collection.find_one(
            {"phone_number": phone_number},
            sort=[("created_at", -1)]
        )
        
        if not last_otp:
            return True
        
        time_diff = datetime.utcnow() - last_otp["created_at"]
        return time_diff.total_seconds() >= OTP_RESEND_COOLDOWN_SECONDS
    except Exception as e:
        print(f"Error checking OTP cooldown: {e}")
        return False

async def get_user_by_phone(phone_number: str) -> Optional[dict]:
    """Get user by phone number"""
    try:
        users = get_user_collection()
        user = await users.find_one({"phone": phone_number})
        return user
    except Exception as e:
        print(f"Error getting user: {e}")
        return None

async def get_user_by_email(email: str) -> Optional[dict]:
    """Get user by email address"""
    try:
        users = get_user_collection()
        user = await users.find_one({"email": email.lower()})
        print(user,"useruser")
        return user
    except Exception as e:
        print(f"Error getting user by email: {e}")
        return None

def generate_password_reset_token() -> str:
    """Generate a secure password reset token"""
    return secrets.token_urlsafe(32)

async def store_password_reset_token(user_id: str, token: str) -> bool:
    """Store password reset token in database"""
    try:
        reset_collection = db['password_reset_tokens']
        expiry_time = datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRY_MINUTES)
        
        # Remove any existing tokens for this user
        await reset_collection.delete_many({"user_id": user_id})
        
        # Store new token
        token_doc = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "token": token,
            "expires_at": expiry_time,
            "created_at": datetime.utcnow()
        }
        await reset_collection.insert_one(token_doc)
        return True
    except Exception as e:
        print(f"Error storing password reset token: {e}")
        return False

async def verify_password_reset_token(token: str) -> Optional[dict]:
    """Verify password reset token and return user info"""
    try:
        reset_collection = db['password_reset_tokens']
        token_doc = await reset_collection.find_one({
            "token": token,
            "expires_at": {"$gt": datetime.utcnow()}
        })
        
        if token_doc:
            return token_doc
        return None
    except Exception as e:
        print(f"Error verifying password reset token: {e}")
        return None

async def delete_password_reset_token(token: str) -> bool:
    """Delete password reset token after use"""
    try:
        reset_collection = db['password_reset_tokens']
        result = await reset_collection.delete_one({"token": token})
        return result.deleted_count > 0
    except Exception as e:
        print(f"Error deleting password reset token: {e}")
        return False

async def send_password_reset_email(email: str, token: str, user_name: str) -> bool:
    """Send password reset email using centralized email service"""
    try:
        # Create reset link
        reset_link = f"https://simbet.websitetestingbox.com/reset-password/?token={token}"
        
        # Email body
        body = f"""
        <html>
  <body>
    <h2>Password Reset Request</h2>
    <p>Hello {user_name},</p>
    <p>We received a request to reset your password for your Betting App account.</p>
    <p>Click the link below to reset your password:</p>
    
    <!-- Added margin for spacing -->
    <p>
      <a href="{reset_link}" 
         style="background-color: #4CAF50; 
                color: white; 
                padding: 14px 20px; 
                text-decoration: none; 
                border-radius: 4px;
                display: inline-block;
                margin: 15px 0;">Reset Password</a>
    </p>
    
    <p><strong>This link will expire in {PASSWORD_RESET_TOKEN_EXPIRY_MINUTES} minutes.</strong></p>
    <p>If you didn't request this password reset, please ignore this email.</p>
    <p>Best regards,<br>Betting App Team</p>
  </body>
</html>
        """
        
        print(f"📧 Attempting to send password reset email to: {email}")
        
        # Use centralized email service
        result = await send_email_centralized(
            to_email=email,
            subject="Password Reset Request - Betting App",
            body=body,
            is_html=True
        )
        
        if result:
            print(f"✅ Password reset email sent to: {email}")
        else:
            print(f"❌ Failed to send password reset email to: {email}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error sending password reset email: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        return False

async def send_email(to_email: str, subject: str, html_content: str) -> bool:
    """Send email using centralized email service (SendGrid)"""
    try:
        print(f"📧 Attempting to send email to: {to_email}")
        
        # Use centralized email service
        result = await send_email_centralized(
            to_email=to_email,
            subject=subject,
            body=html_content,
            is_html=True
        )
        
        if result:
            print(f"✅ Email sent successfully to: {to_email}")
        else:
            print(f"❌ Failed to send email to: {to_email}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        return False

# async def test_smtp_connection() -> bool:
#     """Test SMTP connection and credentials"""
#     try:
#         print(f"🧪 Testing SMTP connection...")
#         print(f"📧 Server: {SMTP_SERVER}")
#         print(f"📧 Port: {SMTP_PORT}")
#         print(f"📧 Username: {SMTP_USERNAME}")
#         print(f"📧 Use SSL: {SMTP_USE_SSL}")
        
#         # Create a simple test message
#         msg = MIMEMultipart()
#         msg['From'] = SMTP_USERNAME
#         msg['To'] = SMTP_USERNAME  # Send to self for testing
#         msg['Subject'] = "SMTP Test - Betting App"
#         msg.attach(MIMEText("This is a test email to verify SMTP configuration.", 'plain'))
        
#         if SMTP_USE_SSL:
#             await aiosmtplib.send(
#                 msg,
#                 hostname=SMTP_SERVER,
#                 port=465,
#                 username=SMTP_USERNAME,
#                 password=SMTP_PASSWORD,
#                 use_tls=True,
#                 validate_certs=False
#             )
#         else:
#             await aiosmtplib.send(
#                 msg,
#                 hostname=SMTP_SERVER,
#                 port=SMTP_PORT,
#                 username=SMTP_USERNAME,
#                 password=SMTP_PASSWORD,
#                 use_tls=True,
#                 start_tls=True,
#                 validate_certs=False
#             )
        
#         print("✅ SMTP test successful!")
#         return True
        
#     except Exception as e:
#         print(f"❌ SMTP test failed: {e}")
#         print(f"❌ Error type: {type(e).__name__}")
#         return False

async def update_user_password(user_id: str, new_password: str) -> bool:
    """Update user password in database"""
    try:
        from bson import ObjectId
        
        users = get_user_collection()
        hashed_password = hash_password(new_password)
        
        print(f"🔐 Updating password for user_id: {user_id}")
        print(f"🔐 User_id type: {type(user_id)}")
        
        # Convert string user_id to ObjectId
        object_id = ObjectId(user_id)
        
        result = await users.update_one(
            {"_id": object_id},
            {"$set": {"password_hash": hashed_password}}
        )
        
        print(f"🔐 Update result - matched: {result.matched_count}, modified: {result.modified_count}")
        
        return result.modified_count > 0
    except Exception as e:
        print(f"❌ Error updating user password: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        return False

# ==================== SOCIAL LOGIN FUNCTIONS ====================

async def validate_google_token(access_token: str) -> dict:
    """Validate Google OAuth token and return user profile"""
    try:
        print(f"🔍 Validating Google token: {access_token[:20]}...")
        
        # Verify token with Google API
        try:
            response = requests.get(
                f"https://www.googleapis.com/oauth2/v3/tokeninfo?access_token={access_token}",
                timeout=10  # Add timeout
            )
            print(f"🔍 Google tokeninfo response status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"❌ Google tokeninfo failed: {response.status_code} - {response.text}")
                raise HTTPException(status_code=401, detail="Invalid Google token")
            
            token_info = response.json()
            print(f"🔍 Google tokeninfo: {token_info}")
            
        except requests.exceptions.Timeout:
            print(f"❌ Google API request timeout")
            raise HTTPException(status_code=401, detail="Google API request timeout")
        except requests.exceptions.ConnectionError:
            print(f"❌ Google API connection error")
            raise HTTPException(status_code=401, detail="Google API connection error")
        except requests.RequestException as e:
            print(f"❌ Google API request failed: {str(e)}")
            raise HTTPException(status_code=401, detail=f"Google API request failed: {str(e)}")
        
        # Verify the token is for our app
        if token_info.get('aud') != GOOGLE_CLIENT_ID:
            print(f"❌ Google client ID mismatch: expected {GOOGLE_CLIENT_ID}, got {token_info.get('aud')}")
            raise HTTPException(status_code=401, detail="Invalid Google client ID")
        
        # Get user profile
        try:
            profile_response = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10  # Add timeout
            )
            print(f"🔍 Google userinfo response status: {profile_response.status_code}")
            
            if profile_response.status_code != 200:
                print(f"❌ Google userinfo failed: {profile_response.status_code} - {profile_response.text}")
                raise HTTPException(status_code=401, detail="Failed to fetch Google profile")
            
            profile = profile_response.json()
            print(f"🔍 Google profile: {profile}")
            
        except requests.exceptions.Timeout:
            print(f"❌ Google userinfo request timeout")
            raise HTTPException(status_code=401, detail="Google userinfo request timeout")
        except requests.exceptions.ConnectionError:
            print(f"❌ Google userinfo connection error")
            raise HTTPException(status_code=401, detail="Google userinfo connection error")
        except requests.RequestException as e:
            print(f"❌ Google userinfo request failed: {str(e)}")
            raise HTTPException(status_code=401, detail=f"Google userinfo request failed: {str(e)}")
        
        # Extract first and last name from Google profile
        full_name = profile.get('name', '')
        first_name = profile.get('given_name', '')
        last_name = profile.get('family_name', '')
        
        print(f"🔍 Google profile raw data - name: '{full_name}', given_name: '{first_name}', family_name: '{last_name}'")
        
        # If first/last names are not available, try to parse from full_name
        if not first_name and not last_name and full_name:
            name_parts = full_name.strip().split()
            if len(name_parts) >= 2:
                first_name = name_parts[0]
                last_name = ' '.join(name_parts[1:])
            elif len(name_parts) == 1:
                first_name = name_parts[0]
                last_name = ""
            print(f"🔍 Parsed names from full_name - first_name: '{first_name}', last_name: '{last_name}'")
        
        # Ensure we have a proper full_name
        if not full_name and (first_name or last_name):
            full_name = f"{first_name} {last_name}".strip()
        
        print(f"🔍 Final extracted names - first_name: '{first_name}', last_name: '{last_name}', full_name: '{full_name}'")
        
        # Validate required fields
        if not profile.get('id'):
            print(f"❌ Google profile missing ID")
            raise HTTPException(status_code=401, detail="Google profile missing user ID")
        
        if not profile.get('email'):
            print(f"❌ Google profile missing email")
            raise HTTPException(status_code=401, detail="Google profile missing email")
        
        result = {
            "provider": "google",
            "provider_user_id": profile.get('id'),
            "email": profile.get('email'),
            "full_name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "profile_picture": profile.get('picture'),
            "email_verified": profile.get('verified_email', False)
        }
        
        print(f"✅ Google validation successful: {result}")
        return result
        
    except requests.RequestException as e:
        print(f"❌ Google API request error: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Google API error: {str(e)}")
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"❌ Unexpected Google validation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Google validation error: {str(e)}")

async def validate_apple_token(id_token: str) -> dict:
    """Validate Apple ID token and return user profile"""
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Apple ID token required."
        )

    try:
        # Fetch Apple public keys
        async with httpx.AsyncClient() as client:
            response = await client.get("https://appleid.apple.com/auth/keys")
            jwks = response.json()

        # Decode header to find correct key
        unverified_header = jwt.get_unverified_header(id_token)
        key = next((k for k in jwks['keys'] if k['kid'] == unverified_header['kid']), None)

        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find matching Apple public key."
            )

        # Convert JWK to PEM format for jose library
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        
        # Construct RSA public key from JWK
        n = int.from_bytes(base64.urlsafe_b64decode(key['n'] + '==='), 'big')
        e = int.from_bytes(base64.urlsafe_b64decode(key['e'] + '==='), 'big')
        
        public_key = rsa.RSAPublicNumbers(e, n).public_key()
        pem_key = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        # Decode JWT with Apple's public key
        payload = jwt.decode(
            id_token,
            pem_key,
            algorithms=['RS256'],
            options={
                "verify_aud": False,  # or set your actual `audience` here
                "verify_at_hash": False  # Skip at_hash validation for Apple ID tokens
            }
        )

        # Extract first and last name from Apple profile
        full_name = payload.get("name", "")
        first_name = payload.get("firstName", "")
        last_name = payload.get("lastName", "")
        
        print(f"🔍 Apple profile raw data - name: '{full_name}', firstName: '{first_name}', lastName: '{last_name}'")
        
        # If first/last names are not available, try to parse from full_name
        if not first_name and not last_name and full_name:
            name_parts = full_name.strip().split()
            if len(name_parts) >= 2:
                first_name = name_parts[0]
                last_name = ' '.join(name_parts[1:])
            elif len(name_parts) == 1:
                first_name = name_parts[0]
                last_name = ""
            print(f"🔍 Parsed names from full_name - first_name: '{first_name}', last_name: '{last_name}'")
        
        # Ensure we have a proper full_name
        if not full_name and (first_name or last_name):
            full_name = f"{first_name} {last_name}".strip()
        
        print(f"🔍 Final extracted names - first_name: '{first_name}', last_name: '{last_name}', full_name: '{full_name}'")
        
        return {
            "provider": "apple",
            "provider_user_id": payload.get("sub"),
            "email": payload.get("email"),
            "full_name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "profile_picture": None,  # Apple doesn't provide profile pictures
            "email_verified": payload.get("email_verified", False),
        }

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"JWT Error: {str(e)}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unexpected Error: {str(e)}"
        )

# async def validate_facebook_token(access_token: str) -> dict:
#     """Validate Facebook OAuth token and return user profile"""
#     try:
#         # Verify token with Facebook API
#         response = requests.get(
#             f"https://graph.facebook.com/me?fields=id,name,email,picture&access_token={access_token}"
#         )
        
#         if response.status_code != 200:
#             raise HTTPException(status_code=401, detail="Invalid Facebook token")
        
#         profile = response.json()
        
#         # Verify the token is for our app
#         app_response = requests.get(
#             f"https://graph.facebook.com/app?access_token={access_token}"
#         )
        
#         if app_response.status_code == 200:
#             app_info = app_response.json()
#             if app_info.get('id') != FACEBOOK_APP_ID:
#                 raise HTTPException(status_code=401, detail="Invalid Facebook app ID")
        
#         return {
#             "provider": "facebook",
#             "provider_user_id": profile.get('id'),
#             "email": profile.get('email'),
#             "full_name": profile.get('name'),
#             "profile_picture": profile.get('picture', {}).get('data', {}).get('url') if profile.get('picture') else None,
#             "email_verified": True  # Facebook emails are verified
#         }
        
#     except requests.RequestException as e:
#         raise HTTPException(status_code=401, detail=f"Facebook API error: {str(e)}")
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Facebook validation error: {str(e)}")

async def validate_social_token(access_token: str, provider: str) -> dict:
    """Validate social login token based on provider"""
    if provider == 'google':
        return await validate_google_token(access_token)
    elif provider == 'apple':
        return await validate_apple_token(access_token)
    # elif provider == 'facebook':
    #     return await validate_facebook_token(access_token)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

async def find_or_create_social_user(profile: dict) -> dict:
    """Find existing user or create new user from social profile"""
    try:
        # Validate profile data
        if not profile or not isinstance(profile, dict):
            raise HTTPException(status_code=400, detail="Invalid profile data")
        
        # Ensure required fields exist
        if not profile.get("provider") or not profile.get("provider_user_id"):
            raise HTTPException(status_code=400, detail="Missing required profile fields: provider or provider_user_id")
        
        # Ensure email exists for new user creation
        if not profile.get("email"):
            raise HTTPException(status_code=400, detail="Email is required for social login")
        
        # Debug: Log the profile data
        print(f"🔍 Processing social login profile: {profile}")
        print(f"🔍 Provider: {profile.get('provider')}")
        print(f"🔍 Provider User ID: {profile.get('provider_user_id')}")
        print(f"🔍 Email: {profile.get('email')}")
        print(f"🔍 First Name: {profile.get('first_name')}")
        print(f"🔍 Last Name: {profile.get('last_name')}")
        print(f"🔍 Full Name: {profile.get('full_name')}")
        
        # Validate that all required fields are strings and not None
        required_fields = ["provider", "provider_user_id", "email"]
        for field in required_fields:
            value = profile.get(field)
            if not value or not isinstance(value, str):
                print(f"❌ Error: Invalid {field} field: {value} (type: {type(value)})")
                raise HTTPException(status_code=400, detail=f"Invalid {field} field: must be a non-empty string")
        
        users_collection = get_user_collection()
        
        # First, try to find by provider user ID
        existing_user = await users_collection.find_one({
            "social_logins.provider": profile.get("provider"),
            "social_logins.provider_user_id": profile.get("provider_user_id")
        })
        
        if existing_user:
            # Check if user has active membership - only allow social login for active users
            membership_status = existing_user.get("membership_status")
            membership_type = existing_user.get("membership_type")
            
            # if not membership_status or membership_status not in ["active"]:
            #     raise HTTPException(
            #         status_code=403, 
            #         detail="Please complete your subscription first."
            #     )
            
            if not membership_type or membership_type not in ["trial", "paid", "free"]:
                raise HTTPException(
                    status_code=403, 
                    detail="Please complete your subscription first."
                )
            
            # User exists and has active membership - update social login info
            update_fields = {}
            
            # Ensure user is marked as social login
            if not existing_user.get('is_social_login', False):
                update_fields["is_social_login"] = True
            
            # Update names if they're missing or empty
            if not existing_user.get('first_name') and profile.get('first_name'):
                update_fields["first_name"] = profile.get('first_name')
            if not existing_user.get('last_name') and profile.get('last_name'):
                update_fields["last_name"] = profile.get('last_name')
            if not existing_user.get('full_name') or existing_user.get('full_name', '').startswith('User_'):
                # Generate proper full_name from first and last names
                first_name = existing_user.get('first_name') or profile.get('first_name', '')
                last_name = existing_user.get('last_name') or profile.get('last_name', '')
                if first_name or last_name:
                    update_fields["full_name"] = f"{first_name} {last_name}".strip()
            
            # Always update last_login for existing users
            update_fields["last_login"] = datetime.utcnow()
            
            if update_fields:
                # Ensure existing_user has _id field
                if not existing_user or "_id" not in existing_user:
                    print(f"❌ Error: existing_user missing _id field: {existing_user}")
                    raise HTTPException(status_code=500, detail="User data corruption: missing _id field")
                
                await users_collection.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": update_fields}
                )
                # Update the existing_user dict with new fields
                existing_user.update(update_fields)
                print(f"✅ Updated existing user with social login info and last_login: {existing_user['_id']}")
                print(f"🔍 Updated user names - first_name: '{existing_user.get('first_name')}', last_name: '{existing_user.get('last_name')}', full_name: '{existing_user.get('full_name')}'")
            
            return existing_user
        
        # If not found by provider ID, try by email
        if profile.get("email"):
            existing_user = await users_collection.find_one({
                "email": profile.get("email").lower()
            })
            
            if existing_user:
                # Check if user has active membership - only allow social login for active users
                membership_status = existing_user.get("membership_status")
                membership_type = existing_user.get("membership_type")
                
                if not membership_status or membership_status not in ["active"]:
                    raise HTTPException(
                        status_code=403, 
                        detail="Please complete your subscription first."
                    )
                
                if not membership_type or membership_type not in ["trial", "paid"]:
                    raise HTTPException(
                        status_code=403, 
                        detail="Please complete your subscription first."
                    )
                
                # User exists and has active membership - link social login
                update_doc = {
                    "$push": {
                        "social_logins": {
                            "provider": profile.get("provider"),
                            "provider_user_id": profile.get("provider_user_id"),
                            "linked_at": datetime.utcnow()
                        }
                    }
                }
                
                # Ensure user is marked as social login
                set_fields = {}
                if not existing_user.get('is_social_login', False):
                    set_fields["is_social_login"] = True
                
                # Update names if they're missing or empty
                if not existing_user.get('first_name') and profile.get('first_name'):
                    set_fields["first_name"] = profile.get('first_name')
                if not existing_user.get('last_name') and profile.get('last_name'):
                    set_fields["last_name"] = profile.get('last_name')
                if not existing_user.get('full_name') or existing_user.get('full_name', '').startswith('User_'):
                    # Generate proper full_name from first and last names
                    first_name = existing_user.get('first_name') or profile.get('first_name', '')
                    last_name = existing_user.get('last_name') or profile.get('last_name', '')
                    if first_name or last_name:
                        set_fields["full_name"] = f"{first_name} {last_name}".strip()
                
                # Always update last_login
                set_fields["last_login"] = datetime.utcnow()
                
                if set_fields:
                    update_doc["$set"] = set_fields
                    # Update the existing_user dict with new fields
                    existing_user.update(set_fields)
                
                # Ensure existing_user has _id field before update
                if not existing_user or "_id" not in existing_user:
                    print(f"❌ Error: existing_user missing _id field in email lookup: {existing_user}")
                    raise HTTPException(status_code=500, detail="User data corruption: missing _id field")
                
                await users_collection.update_one(
                    {"_id": existing_user["_id"]},
                    update_doc
                )
                print(f"✅ Linked social login to existing user: {existing_user['_id']}")
                print(f"🔍 Updated user names - first_name: '{existing_user.get('first_name')}', last_name: '{existing_user.get('last_name')}', full_name: '{existing_user.get('full_name')}'")
                return existing_user
        
        # For new users, don't allow direct social login - they need to subscribe first
        # Instead, create a temporary user record and redirect to subscription
        raise HTTPException(
            status_code=403,
            detail="Please complete your subscription first."
        )
        
    except HTTPException:
        # Re-raise HTTPExceptions as-is (including 403 errors)
        raise
    except Exception as e:
        print(f"❌ Error in find_or_create_social_user: {e}")
        print(f"🔍 Profile data: {profile}")
        print(f"🔍 Error type: {type(e)}")
        import traceback
        print(f"🔍 Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

async def update_user_last_login(user_id: str):
    """Update user's last login timestamp"""
    try:
        users_collection = get_user_collection()
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"last_login": datetime.utcnow()}}
        )
    except Exception as e:
        print(f"❌ Error updating last login: {e}")

async def log_social_login_attempt(provider: str, success: bool, user_id: str = None, error: str = None):
    """Log social login attempts for audit purposes"""
    try:
        log_collection = db['social_login_logs']
        log_entry = {
            "provider": provider,
            "success": success,
            "user_id": user_id,
            "error": error,
            "timestamp": datetime.utcnow(),
            "ip_address": None  # Could be added if request context is available
        }
        await log_collection.insert_one(log_entry)
    except Exception as e:
        print(f"❌ Error logging social login attempt: {e}")

async def update_user_role(user_id: str, role: str) -> dict:
    """Update user role and mark profile as completed"""
    try:
        users_collection = get_user_collection()
        
        # Validate role
        if role not in ['Member', 'Captain']:
            raise HTTPException(status_code=400, detail="Invalid role. Must be 'Member' or 'Captain'")
        
        # Update user with role and mark profile as completed
        # For social login users, completing role selection means they've completed step 2 (profile completion)
        # For regular users, this would be step 2 as well
        update_data = {
            "role": role,
            "is_profile_completed": True,
            "profile_completed_at": datetime.utcnow(),
            "complete_step": 2,  # Profile completed step
            "updated_at": datetime.utcnow()
        }
        
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get updated user
        updated_user = await users_collection.find_one({"_id": ObjectId(user_id)})
        
        return {
            "user_id": str(updated_user["_id"]),
            "full_name": updated_user["full_name"],
            "first_name": updated_user.get("first_name", ""),
            "last_name": updated_user.get("last_name", ""),
            "email": updated_user.get("email"),
            "role": updated_user["role"],
            "is_profile_completed": updated_user["is_profile_completed"],
            "is_social_login": updated_user.get("is_social_login", False),
            "profile_picture": updated_user.get("profile_picture"),
            "social_logins": updated_user.get("social_logins", []),
            "complete_step": updated_user.get("complete_step", 0)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error updating user role: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

async def check_user_profile_status(user_id: str) -> dict:
    """Check if user profile is completed"""
    try:
        users_collection = get_user_collection()
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "user_id": str(user["_id"]),
            "is_profile_completed": user.get("is_profile_completed", False),
            "role": user.get("role"),
            "is_social_login": user.get("is_social_login", False),
            "requires_role_selection": not user.get("is_profile_completed", False) and user.get("is_social_login", False)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error checking user profile status: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# ========================================
# Enhanced Session Management Functions
# ========================================

async def generate_session_id() -> str:
    """Generate a unique session ID"""
    return f"sess_{uuid.uuid4().hex}_{int(time.time())}"

async def blacklist_token(token: str, user_id: str, reason: str = "manual_logout") -> bool:
    """Add token to blacklist for invalidation"""
    try:
        blacklist_collection = get_session_blacklist_collection()
        
        # Decode token to get expiry time
        payload = verify_token(token)
        if not payload:
            return False
        
        expiry_time = datetime.utcfromtimestamp(payload.get("exp", 0))
        
        blacklist_entry = {
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),  # Store hash for security
            "user_id": user_id,
            "blacklisted_at": datetime.utcnow(),
            "expires_at": expiry_time,
            "reason": reason,
            "session_id": payload.get("session_id")
        }
        
        await blacklist_collection.insert_one(blacklist_entry)
        print(f"✅ Token blacklisted for user {user_id}: {reason}")
        return True
        
    except Exception as e:
        print(f"❌ Error blacklisting token: {e}")
        return False

async def is_token_blacklisted(token: str) -> bool:
    """Check if token is blacklisted"""
    try:
        blacklist_collection = get_session_blacklist_collection()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        blacklisted_token = await blacklist_collection.find_one({
            "token_hash": token_hash,
            "expires_at": {"$gt": datetime.utcnow()}
        })
        
        return blacklisted_token is not None
        
    except Exception as e:
        print(f"❌ Error checking token blacklist: {e}")
        return False

async def create_user_session(user_id: str, token: str, device_info: str = None) -> str:
    """Create and store user session information"""
    try:
        sessions_collection = get_active_sessions_collection()
        session_id = await generate_session_id()
        
        # Decode token to get expiry
        payload = verify_token(token)
        expires_at = datetime.utcfromtimestamp(payload.get("exp", 0)) if payload else datetime.utcnow() + timedelta(hours=24)
        
        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "created_at": datetime.utcnow(),
            "last_activity": datetime.utcnow(),
            "expires_at": expires_at,
            "device_info": device_info,
            "is_active": True
        }
        
        await sessions_collection.insert_one(session_data)
        
        # Clean up old sessions for this user (keep only latest MAX_SESSIONS_PER_USER)
        await cleanup_old_user_sessions(user_id)
        
        print(f"✅ Session created for user {user_id}: {session_id}")
        return session_id
        
    except Exception as e:
        print(f"❌ Error creating user session: {e}")
        return ""

async def update_session_activity(user_id: str, session_id: str = None, token: str = None) -> bool:
    """Update last activity timestamp for session"""
    try:
        sessions_collection = get_active_sessions_collection()
        activity_collection = get_session_activity_collection()
        
        # Find session by session_id or token
        query = {}
        if session_id:
            query = {"session_id": session_id, "user_id": user_id}
        elif token:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            query = {"token_hash": token_hash, "user_id": user_id}
        else:
            return False
        
        # Update session last activity
        result = await sessions_collection.update_one(
            query,
            {
                "$set": {
                    "last_activity": datetime.utcnow(),
                    "is_active": True
                }
            }
        )
        
        # Log activity for tracking
        if result.modified_count > 0:
            activity_log = {
                "user_id": user_id,
                "session_id": session_id or "unknown",
                "activity_timestamp": datetime.utcnow(),
                "activity_type": "api_request"
            }
            await activity_collection.insert_one(activity_log)
        
        return result.modified_count > 0
        
    except Exception as e:
        print(f"❌ Error updating session activity: {e}")
        return False

async def invalidate_user_sessions(user_id: str, session_id: str = None, all_devices: bool = False) -> int:
    """Invalidate user sessions (current session or all devices)"""
    try:
        sessions_collection = get_active_sessions_collection()
        
        if all_devices:
            # Invalidate all sessions for user
            query = {"user_id": user_id, "is_active": True}
        elif session_id:
            # Invalidate specific session
            query = {"user_id": user_id, "session_id": session_id, "is_active": True}
        else:
            return 0
        
        # Get sessions to blacklist their tokens
        sessions_to_invalidate = await sessions_collection.find(query).to_list(length=None)
        
        # Blacklist tokens for all sessions being invalidated
        for session in sessions_to_invalidate:
            # We can't retrieve original token from hash, but we mark session as invalid
            pass
        
        # Mark sessions as inactive
        result = await sessions_collection.update_many(
            query,
            {
                "$set": {
                    "is_active": False,
                    "invalidated_at": datetime.utcnow()
                }
            }
        )
        
        print(f"✅ Invalidated {result.modified_count} sessions for user {user_id}")
        return result.modified_count
        
    except Exception as e:
        print(f"❌ Error invalidating user sessions: {e}")
        return 0

async def cleanup_expired_sessions() -> int:
    """Clean up expired sessions and blacklisted tokens"""
    try:
        now = datetime.utcnow()
        
        # Clean expired sessions
        sessions_collection = get_active_sessions_collection()
        sessions_result = await sessions_collection.delete_many({
            "$or": [
                {"expires_at": {"$lt": now}},
                {
                    "last_activity": {"$lt": now - timedelta(minutes=SESSION_INACTIVITY_TIMEOUT_MINUTES)},
                    "is_active": True
                }
            ]
        })
        
        # Clean expired blacklisted tokens
        blacklist_collection = get_session_blacklist_collection()
        blacklist_result = await blacklist_collection.delete_many({
            "expires_at": {"$lt": now}
        })
        
        # Clean old activity logs (keep last 30 days)
        activity_collection = get_session_activity_collection()
        activity_result = await activity_collection.delete_many({
            "activity_timestamp": {"$lt": now - timedelta(days=30)}
        })
        
        total_cleaned = sessions_result.deleted_count + blacklist_result.deleted_count + activity_result.deleted_count
        if total_cleaned > 0:
            print(f"✅ Cleaned up {total_cleaned} expired records (sessions: {sessions_result.deleted_count}, blacklist: {blacklist_result.deleted_count}, activity: {activity_result.deleted_count})")
        
        return total_cleaned
        
    except Exception as e:
        print(f"❌ Error cleaning up expired sessions: {e}")
        return 0

async def cleanup_old_user_sessions(user_id: str) -> int:
    """Keep only the latest MAX_SESSIONS_PER_USER active sessions for a user"""
    try:
        sessions_collection = get_active_sessions_collection()
        
        # Get all active sessions for user, sorted by creation time (newest first)
        user_sessions = await sessions_collection.find({
            "user_id": user_id,
            "is_active": True
        }).sort("created_at", -1).to_list(length=None)
        
        if len(user_sessions) <= MAX_SESSIONS_PER_USER:
            return 0
        
        # Get sessions to remove (oldest ones)
        sessions_to_remove = user_sessions[MAX_SESSIONS_PER_USER:]
        session_ids_to_remove = [session["session_id"] for session in sessions_to_remove]
        
        # Invalidate old sessions
        result = await sessions_collection.update_many(
            {"session_id": {"$in": session_ids_to_remove}},
            {
                "$set": {
                    "is_active": False,
                    "invalidated_at": datetime.utcnow(),
                    "invalidation_reason": "max_sessions_exceeded"
                }
            }
        )
        
        print(f"✅ Cleaned up {result.modified_count} old sessions for user {user_id}")
        return result.modified_count
        
    except Exception as e:
        print(f"❌ Error cleaning up old user sessions: {e}")
        return 0

async def get_user_active_sessions(user_id: str) -> list:
    """Get list of active sessions for a user"""
    try:
        sessions_collection = get_active_sessions_collection()
        
        sessions = await sessions_collection.find({
            "user_id": user_id,
            "is_active": True,
            "expires_at": {"$gt": datetime.utcnow()}
        }).sort("last_activity", -1).to_list(length=None)
        
        formatted_sessions = []
        for session in sessions:
            # Check if session is expired due to inactivity
            inactivity_expired = (
                datetime.utcnow() - session["last_activity"]
            ).total_seconds() > (SESSION_INACTIVITY_TIMEOUT_MINUTES * 60)
            
            if not inactivity_expired:
                time_until_expiry = (session["expires_at"] - datetime.utcnow()).total_seconds() / 60
                formatted_session = {
                    "session_id": session["session_id"],
                    "is_active": True,
                    "user_id": user_id,
                    "last_activity": session["last_activity"].isoformat(),
                    "expires_at": session["expires_at"].isoformat(),
                    "device_info": session.get("device_info", "Unknown Device"),
                    "time_until_expiry_minutes": max(0, int(time_until_expiry))
                }
                formatted_sessions.append(formatted_session)
        
        return formatted_sessions
        
    except Exception as e:
        print(f"❌ Error getting user active sessions: {e}")
        return []

async def check_session_timeout(user_id: str, token: str) -> bool:
    """Check if session has timed out due to inactivity"""
    try:
        sessions_collection = get_active_sessions_collection()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        session = await sessions_collection.find_one({
            "user_id": user_id,
            "token_hash": token_hash,
            "is_active": True
        })
        
        if not session:
            # No session found - this could be a newly generated token
            # Check if the token itself is still valid (not expired)
            try:
                payload = verify_token(token)
                if payload and payload.get("exp"):
                    # Token is still valid, so we'll allow it and create a session later
                    print(f"🔍 No session found for user {user_id}, but token is valid - will create session")
                    return False  # Not expired, allow the request
                else:
                    print(f"⚠️ No session found and token is invalid for user {user_id}")
                    return True  # Token is invalid, consider it expired
            except Exception as token_error:
                print(f"⚠️ Error verifying token: {str(token_error)}")
                return True  # Error verifying token, consider it expired
        
        # Check inactivity timeout
        last_activity = session["last_activity"]
        inactivity_duration = datetime.utcnow() - last_activity
        
        if inactivity_duration.total_seconds() > (SESSION_INACTIVITY_TIMEOUT_MINUTES * 60):
            # Mark session as expired
            await sessions_collection.update_one(
                {"session_id": session["session_id"]},
                {
                    "$set": {
                        "is_active": False,
                        "invalidated_at": datetime.utcnow(),
                        "invalidation_reason": "inactivity_timeout"
                    }
                }
            )
            return True
        
        return False
        
    except Exception as e:
        print(f"❌ Error checking session timeout: {e}")
        return True

async def get_club_count_for_captain(captain_id: str) -> int:
    """Get the club count for a captain using the club service's logic to ensure proper management"""
    try:
        # Import the club service's recalculate function to ensure proper club count management
        # This ensures that once club_count = 1, it never goes back to 0
        try:
            import sys
            import os
            # Add the club service path to sys.path to import the db module
            club_service_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'betting_club_service', 'clubs')
            if club_service_path not in sys.path:
                sys.path.append(club_service_path)
            
            from db import recalculate_captain_club_count
            
            # Use the club service's logic to recalculate and ensure proper club count management
            success = await recalculate_captain_club_count(captain_id)
            if success:
                print(f"✅ Recalculated club count for captain {captain_id}")
            else:
                print(f"⚠️ Failed to recalculate club count for captain {captain_id}")
            
        except ImportError as import_error:
            print(f"⚠️ Could not import club service functions: {import_error}")
            # Fallback to reading stored value if club service is not available
            pass
        except Exception as recalc_error:
            print(f"⚠️ Error recalculating club count: {recalc_error}")
            # Fallback to reading stored value if recalculation fails
            pass
        
        # Get the user's stored club count from the auth database
        users_collection = get_user_collection()
        
        user = await users_collection.find_one({"_id": ObjectId(captain_id)})
        if not user:
            print(f"⚠️ Captain {captain_id} not found in auth database")
            return 0
        
        club_count = user.get("club_count", 0)
        print(f"✅ Retrieved club count {club_count} for captain {captain_id}")
        
        return club_count
        
    except Exception as e:
        print(f"⚠️ Error getting club count for captain {captain_id}: {e}")
        # Return 0 as default if there's an error
        return 0

async def get_club_count_for_member(member_id: str) -> int:
    """Get the club count for a member - starts at 0, becomes 1 when they join first club, stays 1"""
    try:
        # Get the user's stored club count from the auth database
        users_collection = get_user_collection()
        
        user = await users_collection.find_one({"_id": ObjectId(member_id)})
        if not user:
            print(f"⚠️ Member {member_id} not found in auth database")
            return 0
        
        club_count = user.get("club_count", 0)
        print(f"✅ Retrieved club count {club_count} for member {member_id}")
        
        return club_count
        
    except Exception as e:
        print(f"⚠️ Error getting club count for member {member_id}: {e}")
        # Return 0 as default if there's an error
        return 0

async def update_user_club_count(user_id: str, club_count: int) -> bool:
    """Update the club count for a user in the database using club service logic"""
    try:
        # For captains, use the club service's logic to ensure proper club count management
        # This ensures that once club_count = 1, it never goes back to 0
        try:
            import sys
            import os
            # Add the club service path to sys.path to import the db module
            club_service_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'betting_club_service', 'clubs')
            if club_service_path not in sys.path:
                sys.path.append(club_service_path)
            
            from db import recalculate_captain_club_count
            
            # Use the club service's logic to recalculate and ensure proper club count management
            success = await recalculate_captain_club_count(user_id)
            if success:
                print(f"✅ Updated club count using club service logic for user {user_id}")
                return True
            else:
                print(f"⚠️ Failed to update club count using club service logic for user {user_id}")
                # Fallback to direct update
                
        except ImportError as import_error:
            print(f"⚠️ Could not import club service functions: {import_error}")
            # Fallback to direct update if club service is not available
        except Exception as recalc_error:
            print(f"⚠️ Error using club service logic: {recalc_error}")
            # Fallback to direct update if club service logic fails
        
        # Fallback: Direct update (for non-captains or when club service is not available)
        users_collection = get_user_collection()
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"club_count": club_count, "updated_at": datetime.now(timezone.utc)}}
        )
        
        if result.modified_count > 0:
            print(f"✅ Updated club count to {club_count} for user {user_id}")
            return True
        else:
            print(f"⚠️ No changes made to club count for user {user_id}")
            return False
            
    except Exception as e:
        print(f"❌ Error updating club count for user {user_id}: {e}")
        return False

def get_club_count_from_token(token: str) -> int:
    """Extract club_count from JWT token"""
    try:
        payload = verify_token(token)
        if payload and payload.get("role") == "Captain":
            return payload.get("club_count", 0)
        return 0
    except Exception as e:
        print(f"⚠️ Error extracting club_count from token: {e}")
        return 0

async def get_current_user_club_count(user_id: str) -> int:
    """Get the current club count for a user from the database"""
    try:
        users_collection = get_user_collection()
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if user:
            return user.get("club_count", 0)
        return 0
    except Exception as e:
        print(f"⚠️ Error getting current user club count: {e}")
        return 0

async def get_user_by_phone(phone_number: str) -> Optional[dict]:
    """Get user by phone number"""
    try:
        users = get_user_collection()
        user = await users.find_one({"phone": phone_number})
        return user
    except Exception as e:
        print(f"Error getting user: {e}")
        return None

async def get_user_by_email(email: str) -> Optional[dict]:
    """Get user by email address"""
    try:
        users = get_user_collection()
        user = await users.find_one({"email": email.lower()})
        print(user,"useruser")
        return user
    except Exception as e:
        print(f"Error getting user by email: {e}")
        return None
