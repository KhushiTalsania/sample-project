from pydantic import BaseModel, EmailStr, validator, Field, model_validator
from typing import Literal, Optional, List, Dict, Union
from enum import Enum
import re

class UserRegistrationRequest(BaseModel):
    full_name: str = Field(..., min_length=1)
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=15)
    country_code: str = Field(..., description="Country code for phone number (e.g., +1, +91, +44)")
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    re_password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    role: Literal['Member', 'Captain']
    wants_membership: bool = False  # For membership selection during registration
    terms_accepted: bool = Field(False, description="Must accept terms and conditions")

    @validator('full_name')
    def name_no_special_chars(cls, v):
        if not re.match(r'^[A-Za-z ]+$', v):
            raise ValueError('Full Name must contain only letters and spaces')
        return v

    @validator('phone')
    def phone_numeric(cls, v):
        # Clean phone number - remove any non-digit characters
        cleaned_phone = ''.join(c for c in v if c.isdigit())
        
        if not cleaned_phone:
            raise ValueError('Phone Number must contain digits')
        
        # Check if phone number already includes country code (starts with common country codes)
        common_country_codes = ['1', '44', '91', '86', '81', '49', '33', '39', '34', '7', '380', '48', '46', '31', '32', '41', '43', '45', '47', '358', '46', '47', '48', '49', '50', '51', '52', '53', '54', '55', '56', '57', '58', '59', '60', '61', '62', '63', '64', '65', '66', '67', '68', '69', '70', '71', '72', '73', '74', '75', '76', '77', '78', '79', '80', '81', '82', '83', '84', '85', '86', '87', '88', '89', '90', '91', '92', '93', '94', '95', '96', '97', '98', '99']
        
        # If phone starts with a country code, it should be longer
        if any(cleaned_phone.startswith(code) for code in common_country_codes):
            if not (7 <= len(cleaned_phone) <= 15):
                raise ValueError('Phone Number with country code must be 7-15 digits')
        else:
            if not (7 <= len(cleaned_phone) <= 15):
                raise ValueError('Phone Number must be 7-15 digits')
        
        return cleaned_phone

    @validator('country_code')
    def validate_country_code(cls, v):
        # Clean country code - remove any non-digit characters except +
        cleaned_code = ''.join(c for c in v if c.isdigit() or c == '+')
        
        if not cleaned_code:
            raise ValueError('Country code must contain digits or + symbol')
        
        # Ensure country code starts with + or is just digits
        if not (cleaned_code.startswith('+') or cleaned_code.isdigit()):
            raise ValueError('Country code must start with + or be just digits')
        
        # Remove + for storage consistency
        if cleaned_code.startswith('+'):
            cleaned_code = cleaned_code[1:]
        
        return cleaned_code

    @model_validator(mode='after')
    def validate_phone_country_code_combination(self):
        phone = getattr(self, 'phone', None)
        country_code = getattr(self, 'country_code', None)
        
        if phone and country_code:
            # Clean both values
            clean_phone = ''.join(c for c in phone if c.isdigit())
            clean_country_code = ''.join(c for c in country_code if c.isdigit())
            
            # Check if phone already starts with country code
            if clean_phone.startswith(clean_country_code):
                # Phone already has country code, so we shouldn't add it again
                print(f"⚠️ Warning: Phone number {clean_phone} already contains country code {clean_country_code}")
            
            # Ensure total length is reasonable (country code + phone should be 7-15 digits)
            total_length = len(clean_country_code) + len(clean_phone)
            if total_length < 7 or total_length > 15:
                raise ValueError(f'Total phone number length (country code + phone) must be 7-15 digits, got {total_length}')
        
        return self

    @validator('password')
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must include at least one uppercase letter (A-Z)')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must include at least one lowercase letter (a-z)')
        if not re.search(r'\d', v):
            raise ValueError('Password must include at least one number (0-9)')
        if not re.search(r'[^A-Za-z0-9]', v):
            raise ValueError('Password must include at least one special character (!@#$%^&*(),.?":{}|<>)')
        return v

    @validator('re_password')
    def passwords_match(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError('Passwords do not match')
        return v
    
    @validator('terms_accepted')
    def terms_must_be_accepted(cls, v, values):
        if values.get('wants_membership') and not v:
            raise ValueError('Terms and conditions must be accepted for membership')
        return v

class UserRegistrationResponse(BaseModel):
    message: str
    user_id: Optional[str] = None
    error: Optional[str] = None
    requires_membership: bool = False  # Indicates if user should be redirected to membership plan
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = 0
    membership_status: Optional[str] = None
    status: Optional[str] = None
    wants_membership: bool = False
    user: Optional[dict] = None  # Complete user information (excluding password)
    
    # Stripe Connect fields for Captain registration
    stripe_connect_account_id: Optional[str] = None
    stripe_onboarding_url: Optional[str] = None
    stripe_connect_status: Optional[str] = None

# Account Status Enum for filtering users by status
class AccountStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"

# Email + Password Login Models
class EmailPasswordLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    remember_me: bool = False
    fcm_token: Optional[str] = Field(None, description="FCM device token for push notifications")
    device_type: Optional[str] = Field(None, description="Device type (e.g., android, ios, web)")
    device_name: Optional[str] = Field(None, description="Device name or model")
    device_id: Optional[str] = Field(None, description="Unique device identifier")

    @validator('password')
    def password_not_empty(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Password cannot be empty')
        return v

class EmailPasswordLoginResponse(BaseModel):
    message: str
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int
    user: Optional[dict] = None
    error: Optional[str] = None
    
    # Stripe Connect fields for Captain login validation
    stripe_connect_account_id: Optional[str] = None
    stripe_onboarding_url: Optional[str] = None
    stripe_connect_status: Optional[str] = None
    stripe_onboarding_incomplete: Optional[bool] = None
    charges_enabled: Optional[bool] = None
    payouts_enabled: Optional[bool] = None

# Refresh Token Models
class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., description="Valid refresh token to exchange for new access token")

class RefreshTokenResponse(BaseModel):
    message: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Optional[dict] = None
    error: Optional[str] = None

# Forgot Password Models
class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ForgotPasswordResponse(BaseModel):
    message: str
    success: bool
    error: Optional[str] = None

# Profile Completion After Subscription Models
class ProfileCompletionRequest(BaseModel):
    email: str
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=10, max_length=15)
    country_code: str = Field(..., description="Country code for phone number (e.g., +1, +91, +44)")
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    re_password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    role: Optional[Literal['Member', 'Captain']] = Field(None, description="User role - Member or Captain (optional)")
    fcm_token: Optional[str] = Field(None, description="FCM device token for push notifications")
    device_type: Optional[str] = Field(None, description="Device type (e.g., android, ios, web)")
    device_name: Optional[str] = Field(None, description="Device name or model")
    device_id: Optional[str] = Field(None, description="Unique device identifier")
    verify_token: Optional[str] = Field(None, description="Verification token for email verification")
    user_id: Optional[str] = Field(None, description="User ID for social login profile completion")
    access_token: Optional[str] = Field(None, description="Existing access token to use instead of generating new one")
    refresh_token: Optional[str] = Field(None, description="Existing refresh token to use instead of generating new one")

    @validator('first_name')
    def first_name_no_special_chars(cls, v):
        if not re.match(r'^[A-Za-z ]+$', v):
            raise ValueError('First Name must contain only letters and spaces')
        return v

    @validator('last_name')
    def last_name_no_special_chars(cls, v):
        if not re.match(r'^[A-Za-z ]+$', v):
            raise ValueError('Last Name must contain only letters and spaces')
        return v

    @validator('phone')
    def phone_numeric(cls, v):
        # Clean phone number - remove any non-digit characters
        cleaned_phone = ''.join(c for c in v if c.isdigit())
        
        if not cleaned_phone:
            raise ValueError('Phone Number must contain digits')
        
        # Check if phone number already includes country code (starts with common country codes)
        common_country_codes = ['1', '44', '91', '86', '81', '49', '33', '39', '34', '7', '380', '48', '46', '31', '32', '41', '43', '45', '47', '358', '46', '47', '48', '49', '50', '51', '52', '53', '54', '55', '56', '57', '58', '59', '60', '61', '62', '63', '64', '65', '66', '67', '68', '69', '70', '71', '72', '73', '74', '75', '76', '77', '78', '79', '80', '81', '82', '83', '84', '85', '86', '87', '88', '89', '90', '91', '92', '93', '94', '95', '96', '97', '98', '99']
        
        # If phone starts with a country code, it should be longer
        if any(cleaned_phone.startswith(code) for code in common_country_codes):
            if not (7 <= len(cleaned_phone) <= 15):
                raise ValueError('Phone Number with country code must be 7-15 digits')
        else:
            if not (7 <= len(cleaned_phone) <= 15):
                raise ValueError('Phone Number must be 7-15 digits')
        
        return cleaned_phone

    @validator('country_code')
    def validate_country_code(cls, v):
        # Clean country code - remove any non-digit characters except +
        cleaned_code = ''.join(c for c in v if c.isdigit() or c == '+')
        
        if not cleaned_code:
            raise ValueError('Country code must contain digits or + symbol')
        
        # Ensure country code starts with + or is just digits
        if not (cleaned_code.startswith('+') or cleaned_code.isdigit()):
            raise ValueError('Country code must start with + or be just digits')
        
        # Remove + for storage consistency
        if cleaned_code.startswith('+'):
            cleaned_code = cleaned_code[1:]
        
        return cleaned_code

    @model_validator(mode='after')
    def validate_phone_country_code_combination(self):
        phone = self.phone
        country_code = self.country_code
        
        if phone and country_code:
            # Clean both values
            clean_phone = ''.join(c for c in phone if c.isdigit())
            clean_country_code = ''.join(c for c in country_code if c.isdigit())
            
            # Check if phone already starts with country code
            if clean_phone.startswith(clean_country_code):
                # Phone already has country code, so we shouldn't add it again
                print(f"⚠️ Warning: Phone number {clean_phone} already contains country code {clean_country_code}")
            
            # Ensure total length is reasonable (country code + phone should be 7-15 digits)
            total_length = len(clean_country_code) + len(clean_phone)
            if total_length < 7 or total_length > 15:
                raise ValueError(f'Total phone number length (country code + phone) must be 7-15 digits, got {total_length}')
        
        return self

    @validator('password')
    def password_strength(cls, v):
        if (len(v) < 8 or
            not re.search(r'[A-Z]', v) or
            not re.search(r'[a-z]', v) or
            not re.search(r'\d', v) or
            not re.search(r'[^A-Za-z0-9]', v)):
            raise ValueError('Password must be at least 8 characters, include uppercase, lowercase, number, and special character')
        return v

    @validator('re_password')
    def passwords_match(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError('Passwords do not match')
        return v

class ProfileCompletionResponse(BaseModel):
    success: bool
    message: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict
    is_completed_profile: Optional[bool] = None
    
    # Stripe Connect fields for Captain profile completion
    stripe_connect_account_id: Optional[str] = None
    stripe_onboarding_url: Optional[str] = None
    stripe_connect_status: Optional[str] = None
    
    # FCM token fields
    fcm_token: Optional[str] = None
    device_type: Optional[str] = None
    device_name: Optional[str] = None
    device_id: Optional[str] = None

# Moderator Profile Completion Models
class ModeratorProfileCompletionRequest(BaseModel):
    signup_token: str = Field(..., min_length=1, description="Moderator signup token")
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=10, max_length=15)
    country_code: str = Field(..., description="Country code for phone number (e.g., +1, +91, +44)")
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    re_password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    fcm_token: Optional[str] = Field(None, description="FCM device token for push notifications")
    device_type: Optional[str] = Field(None, description="Device type (e.g., android, ios, web)")
    device_name: Optional[str] = Field(None, description="Device name or model")
    device_id: Optional[str] = Field(None, description="Unique device identifier")

    @validator('first_name')
    def first_name_no_special_chars(cls, v):
        if not re.match(r'^[A-Za-z ]+$', v):
            raise ValueError('First Name must contain only letters and spaces')
        return v

    @validator('last_name')
    def last_name_no_special_chars(cls, v):
        if not re.match(r'^[A-Za-z ]+$', v):
            raise ValueError('Last Name must contain only letters and spaces')
        return v

    @validator('phone')
    def phone_numeric(cls, v):
        # Clean phone number - remove any non-digit characters
        cleaned_phone = re.sub(r'\D', '', v)
        
        if not cleaned_phone:
            raise ValueError('Phone Number must contain digits')
        
        # Check if phone number already includes country code (starts with common country codes)
        common_country_codes = ['1', '44', '91', '86', '81', '49', '33', '39', '34', '7', '380', '48', '46', '31', '32', '41', '43', '45', '47', '358', '46', '47', '48', '49', '50', '51', '52', '53', '54', '55', '56', '57', '58', '59', '60', '61', '62', '63', '64', '65', '66', '67', '68', '69', '70', '71', '72', '73', '74', '75', '76', '77', '78', '79', '80', '81', '82', '83', '84', '85', '86', '87', '88', '89', '90', '91', '92', '93', '94', '95', '96', '97', '98', '99']
        
        # If phone starts with a country code, it should be longer
        if any(cleaned_phone.startswith(code) for code in common_country_codes):
            if not (7 <= len(cleaned_phone) <= 15):
                raise ValueError('Phone Number with country code must be 7-15 digits')
        else:
            if not (7 <= len(cleaned_phone) <= 15):
                raise ValueError('Phone Number must be 7-15 digits')
        
        return cleaned_phone

    @validator('country_code')
    def validate_country_code(cls, v):
        # Clean country code - remove any non-digit characters except +
        cleaned_code = re.sub(r'[^\d+]', '', v)
        
        if not cleaned_code:
            raise ValueError('Country code must contain digits')
        
        # Ensure it starts with + if it doesn't already
        if not cleaned_code.startswith('+'):
            cleaned_code = '+' + cleaned_code
        
        # Validate length (should be 2-4 digits after +)
        digits_only = cleaned_code[1:]  # Remove the +
        if not (1 <= len(digits_only) <= 4):
            raise ValueError('Country code must be 1-4 digits')
        
        return cleaned_code

    @model_validator(mode='after')
    def validate_phone_country_code_combination(self):
        # Clean phone number for calculation
        cleaned_phone = re.sub(r'\D', '', self.phone)
        cleaned_country_code = re.sub(r'\D', '', self.country_code)
        
        # Calculate total length
        total_length = len(cleaned_phone) + len(cleaned_country_code)
        
        # Check if total length is reasonable (7-15 digits total)
        if not (7 <= total_length <= 15):
            raise ValueError(f'Combined phone number and country code must be 7-15 digits total, got {total_length}')
        
        return self

    @validator('password')
    def password_strength(cls, v):
        if (len(v) < 8 or
            not re.search(r'[A-Z]', v) or
            not re.search(r'[a-z]', v) or
            not re.search(r'\d', v) or
            not re.search(r'[^A-Za-z0-9]', v)):
            raise ValueError('Password must be at least 8 characters, include uppercase, lowercase, number, and special character')
        return v

    @validator('re_password')
    def passwords_match(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError('Passwords do not match')
        return v

# Reset Password Models
class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    confirm_password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")

    @validator('new_password')
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must include at least one uppercase letter (A-Z)')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must include at least one lowercase letter (a-z)')
        if not re.search(r'\d', v):
            raise ValueError('Password must include at least one number (0-9)')
        if not re.search(r'[^A-Za-z0-9]', v):
            raise ValueError('Password must include at least one special character (!@#$%^&*(),.?":{}|<>)')
        return v

    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('Passwords do not match')
        return v

class ResetPasswordResponse(BaseModel):
    message: str
    success: bool
    error: Optional[str] = None

# OTP Login Models
class SendOTPRequest(BaseModel):
    phone_number: str = Field(..., min_length=10, max_length=15)
    country_code: str = Field(..., description="Country code for phone number (e.g., 91, 1, 44)")
    
    @validator('phone_number')
    def phone_numeric(cls, v):
        if not v.isdigit():
            raise ValueError('Phone Number must be numeric')
        if not (10 <= len(v) <= 15):
            raise ValueError('Phone Number must be 10-15 digits')
        return v
    
    @validator('country_code')
    def country_code_numeric(cls, v):
        if not v.isdigit():
            raise ValueError('Country code must be numeric')
        if len(v) < 1 or len(v) > 4:
            raise ValueError('Country code must be 1-4 digits')
        return v

class SendOTPResponse(BaseModel):
    message: str
    success: bool
    error: Optional[str] = None

class VerifyOTPRequest(BaseModel):
    phone_number: str = Field(..., min_length=10, max_length=15)
    country_code: str = Field(..., description="Country code for phone number (e.g., 91, 1, 44)")
    otp: str = Field(..., min_length=6, max_length=6)
    remember_me: bool = False
    fcm_token: Optional[str] = Field(None, description="FCM device token for push notifications")
    device_type: Optional[str] = Field(None, description="Device type (e.g., android, ios, web)")
    device_name: Optional[str] = Field(None, description="Device name or model")
    device_id: Optional[str] = Field(None, description="Unique device identifier")
    
    @validator('phone_number')
    def phone_numeric(cls, v):
        if not v.isdigit():
            raise ValueError('Phone Number must be numeric')
        if not (10 <= len(v) <= 15):
            raise ValueError('Phone Number must be 10-15 digits')
        return v
    
    @validator('country_code')
    def country_code_numeric(cls, v):
        if not v.isdigit():
            raise ValueError('Country code must be numeric')
        if len(v) < 1 or len(v) > 4:
            raise ValueError('Country code must be 1-4 digits')
        return v
    
    @validator('otp')
    def otp_numeric(cls, v):
        if not v.isdigit():
            raise ValueError('OTP must be numeric')
        if len(v) != 6:
            raise ValueError('OTP must be exactly 6 digits')
        return v

class LoginResponse(BaseModel):
    message: str
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int
    user: Optional[dict] = None
    error: Optional[str] = None

class ResendOTPRequest(BaseModel):
    phone_number: str = Field(..., min_length=10, max_length=15)
    country_code: str = Field(..., description="Country code for phone number (e.g., 91, 1, 44)")
    
    @validator('phone_number')
    def phone_numeric(cls, v):
        if not v.isdigit():
            raise ValueError('Phone Number must be numeric')
        if not (10 <= len(v) <= 15):
            raise ValueError('Phone Number must be 10-15 digits')
        return v
    
    @validator('country_code')
    def country_code_numeric(cls, v):
        if not v.isdigit():
            raise ValueError('Country code must be numeric')
        if len(v) < 1 or len(v) > 4:
            raise ValueError('Country code must be 1-4 digits')
        return v

# Trial Membership Models
class TrialOfferDetails(BaseModel):
    title: str
    subtitle: str
    price: float
    duration: int  # days
    weekly_limit: int
    max_clubs: int
    benefits: List[str]
    cta_label: str
    refund_days: int = 7

class CaptainTrialOfferDetails(BaseModel):
    title: str
    subtitle: str
    price: float
    duration: int  # days
    benefits: List[str]
    cta_label: str
    refund_days: int = 7

class TrialMembershipRequest(BaseModel):
    user_id: str
    payment_method_id: str
    skip_trial: bool = False

# Club Membership Details API Models
class ClubMembershipDetailsResponse(BaseModel):
    # Club Information
    club_id: str
    club_name: str
    club_logo: Optional[str] = None
    captain_name: str
    captain_profile_image: Optional[str] = None
    captain_bio: Optional[str] = None
    
    # Membership Plan Details
    plan_type: str  # Trial / Monthly / Premium
    price: float
    membership_benefits: List[str]
    
    # User Subscription Information
    is_user_subscribed: bool
    subscription_status: str  # Active / Cancelled / Expired / Not Subscribed
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    
    # CTA Flags
    show_purchase_cta: bool
    show_cancel_cta: bool
    
    # Additional Info
    win_rate: float = 0.0
    total_picks: int = 0
    member_count: int = 0
    category: Optional[str] = None

# User Active Memberships API Models
class ActiveMembershipItem(BaseModel):
    club_id: str
    club_name: str
    club_logo: Optional[str] = None
    captain_name: str
    captain_profile_pic: Optional[str] = None
    membership_type: str  # "Trial" or "Paid"
    start_date: str
    next_renewal_date: Optional[str] = None
    price: float
    status: str  # "Active", "Paused", "Canceled"
    price_id: Optional[str] = None
    subscription_id: Optional[str] = None

class ActiveMembershipsResponse(BaseModel):
    user_id: str
    total_memberships: int
    active_memberships: List[ActiveMembershipItem]
    message: str

# User Past Memberships API Models
class PastMembershipItem(BaseModel):
    club_id: str
    club_name: str
    club_logo_url: Optional[str] = None
    captain_name: str
    captain_image_url: Optional[str] = None
    membership_type: str  # "trial" or "paid"
    price: str  # e.g., "$19.95/month" or "Free"
    start_date: str
    end_date: str
    status: str  # "expired", "canceled", "trial_expired"
    price_id: Optional[str] = None
    subscription_id: Optional[str] = None

class PastMembershipsResponse(BaseModel):
    user_id: str
    total_past_memberships: int
    past_memberships: List[PastMembershipItem]
    message: str

# Club Join Membership API Models
class JoinClubRequest(BaseModel):
    club_id: str
    price_plan: str  # "monthly", "quarterly", "yearly"
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None    

class JoinClubResponse(BaseModel):
    status: str  # "success", "failed", "already_member"
    message: str
    checkout_url: Optional[str] = None
    session_id: Optional[str] = None
    redirect_url: Optional[str] = None
    price_id: Optional[str] = None
    product_id: Optional[str] = None

class AddClubMemberRequest(BaseModel):
    user_id: str
    club_id: str
    payment_status: str  # "success", "failed"
    transaction_id: Optional[str] = None
    price_id: Optional[str] = None
    subscription_id: Optional[str] = None

class AddClubMemberResponse(BaseModel):
    status: str  # "success", "failed"
    message: str
    redirect_url: Optional[str] = None
    membership_details: Optional[dict] = None

class ClubMembershipStatusResponse(BaseModel):
    club_id: str
    user_id: str
    is_member: bool
    membership_status: str  # "active", "inactive", "not_member"
    subscription_id: Optional[str] = None
    joined_date: Optional[str] = None
    next_billing_date: Optional[str] = None
    price_plan: Optional[str] = None
    amount_paid: Optional[float] = None
    price_id: Optional[str] = None

class TrialMembershipResponse(BaseModel):
    message: str
    success: bool
    trial_id: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None
    client_secret: Optional[str] = None
    error: Optional[str] = None

class TrialRefundRequest(BaseModel):
    user_id: str
    trial_id: str
    reason: Optional[str] = None

class TrialRefundResponse(BaseModel):
    message: str
    success: bool
    refund_id: Optional[str] = None
    amount_refunded: Optional[float] = None
    error: Optional[str] = None

class TrialStatusResponse(BaseModel):
    user_id: str
    trial_used: bool
    membership_status: str  # "active", "expired", "none"
    trial_start_date: Optional[str] = None
    trial_end_date: Optional[str] = None
    clubs_joined: int
    weekly_joins_remaining: int
    total_joins_remaining: int
    can_refund: bool
    refund_deadline: Optional[str] = None

# Social Login Models
class SocialLoginRequest(BaseModel):
    access_token: str
    provider: Literal['google', 'apple', 'facebook']
    fcm_token: Optional[str] = Field(None, description="FCM device token for push notifications")
    device_type: Optional[str] = Field(None, description="Device type (e.g., android, ios, web)")
    device_name: Optional[str] = Field(None, description="Device name or model")
    device_id: Optional[str] = Field(None, description="Unique device identifier")

class SocialUserProfile(BaseModel):
    provider: str
    provider_user_id: str
    email: str
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_picture: Optional[str] = None
    email_verified: bool = False

class SocialLoginResponse(BaseModel):
    message: str
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int
    user: Optional[dict] = None
    is_new_user: bool = False
    requires_role_selection: bool = False
    is_completed_profile: bool = False
    error: Optional[str] = None
    membership_status: Optional[str] = None
    membership_type: Optional[str] = None
    
    # Stripe Connect fields for Captain social login validation
    stripe_connect_account_id: Optional[str] = None
    stripe_onboarding_url: Optional[str] = None
    stripe_connect_status: Optional[str] = None
    charges_enabled: Optional[bool] = None
    payouts_enabled: Optional[bool] = None
    details_submitted: Optional[bool] = None
    remediation_required: Optional[bool] = None
    remediation_message: Optional[str] = None

# ========================================
# Enhanced Logout & Session Management Models
# ========================================

class LogoutRequest(BaseModel):
    """Enhanced logout request with optional session details"""
    all_devices: bool = Field(False, description="Logout from all devices")
    device_id: Optional[str] = Field(None, description="Device identifier for tracking")
    device_token: Optional[str] = Field(None, description="FCM device token to remove on logout")
    reason: Optional[str] = Field(None, description="Logout reason (manual/timeout)")

class LogoutResponse(BaseModel):
    """Enhanced logout response with session details"""
    message: str
    success: bool
    sessions_invalidated: int = 0
    all_devices: bool = False
    timestamp: str
    error: Optional[str] = None

class SessionStatus(BaseModel):
    """Current session status information"""
    is_active: bool
    user_id: str
    last_activity: str
    expires_at: str
    device_info: Optional[str] = None
    session_id: str
    time_until_expiry_minutes: int

class SessionListResponse(BaseModel):
    """List of active sessions for a user"""
    user_id: str
    total_sessions: int
    current_session_id: str
    sessions: List[SessionStatus]
    message: str

class SessionTimeoutResponse(BaseModel):
    """Response when session times out due to inactivity"""
    message: str
    success: bool
    reason: str = "inactivity_timeout"
    timeout_minutes: int = 30
    last_activity: str
    timestamp: str

# ========================================
# User Completion Status Models
# ========================================

class UserCompletionStatusResponse(BaseModel):
    """Response model for user completion status endpoint"""
    message: str
    user_id: str
    complete_step: int = Field(..., description="Current completion step: 0=visited, 1=payment, 2=signup, 3=joined club")
    steps_completed: List[str] = Field(..., description="List of completed steps")
    steps_remaining: List[str] = Field(..., description="List of remaining steps")
    progress_percentage: float = Field(..., description="Percentage of steps completed")
    next_step: str = Field(..., description="Next step to complete")
    user: dict = Field(..., description="User information (excluding sensitive data)")

class MyProfileResponse(BaseModel):
    """Response model for my-profile API"""
    success: bool
    message: str
    data: Optional[dict] = None

# ========================================
# Refund API Models
# ========================================

class RefundRequest(BaseModel):
    """Request model for refund processing"""
    reason: Optional[str] = Field(None, description="Optional reason for refund request")

class RefundResponse(BaseModel):
    """Response model for refund processing"""
    success: bool
    message: str
    refund_amount: Optional[float] = None
    processing_fee: Optional[float] = None
    net_refund: Optional[float] = None
    stripe_refund_id: Optional[str] = None
    refund_processed_at: Optional[str] = None
    refund_details: Optional[Dict] = None
    reactivation_message: Optional[str] = None
    is_reactive: bool = False  # Default to false, true after successful refund
    refund_count: int = 1  # Number of times user has been refunded (default 1 for successful refund)
    error: Optional[str] = None

class RefundStatusResponse(BaseModel):
    """Response model for refund status check"""
    success: bool
    message: str
    user_id: str
    is_refunded: bool
    membership_status: str
    membership_type: str
    refund_eligible: bool = False
    refund_deadline: Optional[str] = None
    can_request_refund: bool = False
    first_trial_join_date: Optional[str] = None
    refund_type: Optional[str] = None  # "membership_purchase" or "trial_club_join"
    refund_amount: Optional[float] = None
    refund_processed_at: Optional[str] = None
    refund_reason: Optional[str] = None
    stripe_refund_id: Optional[str] = None
    refund_details: Optional[Dict] = None
    is_reactive: bool = False  # Default to false, true after successful refund
    refund_count: int = 0  # Number of times user has been refunded
    error: Optional[str] = None

# ========================================
# Profile Update API Models
# ========================================

class UpdateProfileRequest(BaseModel):
    """Request model for profile updates"""
    first_name: Optional[str] = Field(None, description="First name", min_length=1)
    last_name: Optional[str] = Field(None, description="Last name", min_length=1)
    phone: Optional[str] = Field(None, description="Phone number")
    country_code: Optional[str] = Field(None, description="Country code")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")
    bio: Optional[str] = Field(None, description="User bio/biography", max_length=500)

class SubscriptionDetailsResponse(BaseModel):
    """Response model for subscription details"""
    success: bool
    message: str
    data: Optional[Dict] = None
    error: Optional[str] = None

class PaymentCardDetailsResponse(BaseModel):
    """Response model for payment card details"""
    success: bool
    message: str
    data: Optional[Dict] = None
    error: Optional[str] = None

class AddPaymentCardRequest(BaseModel):
    """Request model for adding a payment card"""
    card_number: str = Field(..., description="Card number (16 digits)")
    exp_month: int = Field(..., ge=1, le=12, description="Expiration month (1-12)")
    exp_year: int = Field(..., ge=2024, le=2050, description="Expiration year")
    cvc: str = Field(..., min_length=3, max_length=4, description="Card security code")
    cardholder_name: str = Field(..., min_length=1, description="Name on the card")
    set_as_default: bool = Field(False, description="Whether to set this card as the default payment method")
    
    @validator('card_number')
    def validate_card_number(cls, v):
        # Remove any spaces or dashes
        cleaned_number = ''.join(c for c in v if c.isdigit())
        
        if not cleaned_number:
            raise ValueError('Card number must contain digits')
        
        if len(cleaned_number) < 13 or len(cleaned_number) > 19:
            raise ValueError('Card number must be 13-19 digits')
        
        return cleaned_number
    
    @validator('cvc')
    def validate_cvc(cls, v):
        # Remove any spaces or dashes
        cleaned_cvc = ''.join(c for c in v if c.isdigit())
        
        if not cleaned_cvc:
            raise ValueError('CVC must contain digits')
        
        if len(cleaned_cvc) < 3 or len(cleaned_cvc) > 4:
            raise ValueError('CVC must be 3-4 digits')
        
        return cleaned_cvc
    
    @validator('cardholder_name')
    def validate_cardholder_name(cls, v):
        if not re.match(r'^[A-Za-z ]+$', v):
            raise ValueError('Cardholder name must contain only letters and spaces')
        return v.strip()

# ========================================
# Order History API Models
# ========================================

class OrderHistoryItem(BaseModel):
    """Individual order history item"""
    order_id: str
    order_type: str  # "platform_fee", "club_membership", or "club_payment"
    payment_date: str
    membership_type: str
    amount: float
    currency: str
    status: str
    membership_status: str
    club_name: Optional[str] = None
    club_id: Optional[str] = None
    payment_id: Optional[str] = None
    subscription_id: Optional[str] = None
    pricing_plan: Optional[str] = None
    payment_method: Optional[str] = "Card"
    receipt_url: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    created_at: str
    updated_at: str

class OrderHistoryResponse(BaseModel):
    """Response model for order history"""
    success: bool
    message: str
    data: Optional[Dict] = None
    error: Optional[str] = None

class OrderHistoryRequest(BaseModel):
    """Request model for order history with pagination"""
    page: int = Field(1, ge=1, description="Page number (starts from 1)")
    page_size: int = Field(10, ge=1, le=100, description="Number of items per page (max 100)")
    order_type: Optional[str] = Field(None, description="Filter by order type: 'platform_fee', 'club_membership', or 'club_payment'")

# ========================================
# JOINED CLUBS API MODELS
# ========================================

class JoinedClubItem(BaseModel):
    """Individual joined club item"""
    club_id: str
    club_name: str
    name_based_id: str
    description: Optional[str] = None
    club_status: str
    membership_type: str  # "trial" or "paid"
    membership_status: str  # "active" or "inactive"
    join_date: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    pricing_plan: Optional[str] = None
    amount_paid: Optional[float] = None
    payment_id: Optional[str] = None
    is_active: bool
    created_at: str
    updated_at: str

class JoinedClubsResponse(BaseModel):
    """Response model for joined clubs"""
    success: bool
    message: str
    data: Optional[Dict] = None
    error: Optional[str] = None

class JoinedClubsRequest(BaseModel):
    """Request model for joined clubs with pagination and filtering"""
    page: int = Field(1, ge=1, description="Page number (starts from 1)")
    page_size: int = Field(10, ge=1, le=100, description="Number of items per page (max 100)")
    sort_by: str = Field("join_date", description="Sort by: 'join_date', 'club_name', or 'status'")
    sort_order: str = Field("desc", description="Sort order: 'asc' or 'desc'")
    status_filter: str = Field("all", description="Filter by status: 'all', 'active', or 'inactive'")

# ========================================
# SUPPORT & FEEDBACK API MODELS
# ========================================

class SupportFeedbackRequest(BaseModel):
    """Request model for support and feedback submission"""
    first_name: str = Field(..., min_length=1, max_length=100, description="First name of the user")
    email: str = Field(..., description="Email address of the user")
    subject: str = Field(..., min_length=1, max_length=200, description="Brief description of the inquiry")
    message: str = Field(..., min_length=1, max_length=5000, description="Detailed message")
    type: str = Field(..., description="Type of support request: 'club' or 'platform'")
    selected_club: Optional[str] = Field(None, description="Club name_based_id if type is 'club'")

class SupportFeedbackResponse(BaseModel):
    """Response model for support and feedback submission"""
    success: bool
    message: str
    data: Optional[Dict] = None
    error: Optional[str] = None

# ========================================
# CAPTAIN MEMBERS API MODELS
# ========================================

class CaptainMemberItem(BaseModel):
    """Individual member item for Captain's clubs"""
    member_id: str
    member_name: str
    member_email: str
    member_phone: Optional[str] = None
    member_avatar_url: Optional[str] = None
    club_id: str
    club_name: str
    club_name_based_id: str
    membership_type: str  # "trial" or "paid"
    membership_status: str  # "active" or "inactive"
    join_date: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    amount_paid: Optional[float] = None
    pricing_plan: Optional[str] = None
    is_active: bool
    created_at: str
    updated_at: str

class CaptainModeratorItem(BaseModel):
    """Individual moderator item for Captain's clubs"""
    moderator_id: str
    moderator_name: str
    moderator_email: str
    club_id: str
    club_name: str
    club_name_based_id: str
    type_of_moderator: str  # "free" or "paid"
    status: str  # "active" or "inactive"
    price: Optional[float] = None
    invited_at: str
    responded_at: Optional[str] = None
    response: Optional[str] = None
    is_active: bool

class CaptainMembersResponse(BaseModel):
    """Response model for captain members"""
    success: bool
    message: str
    data: Optional[Dict] = None
    error: Optional[str] = None

class CaptainMembersRequest(BaseModel):
    """Request model for captain members with pagination and filtering"""
    page: int = Field(1, ge=1, description="Page number (starts from 1)")
    page_size: int = Field(10, ge=1, le=100, description="Number of items per page (max 100)")
    search: Optional[str] = Field(None, description="Search by email, club name, or member name")
    status_filter: str = Field("all", description="Filter by status: 'all', 'active', or 'inactive'")
    plan_type: str = Field("all", description="Filter by plan type: 'all', 'trial', or 'paid'")
    club_filter: str = Field("all", description="Filter by specific club (club_id or 'all')")
    role_filter: str = Field("Member", description="Filter by role: 'Member' or 'Moderator'")
    moderator_type_filter: str = Field("all", description="Filter by moderator type: 'all', 'free', or 'paid' (only when role_filter=Moderator)")
    sort_by: str = Field("newest", description="Sort by: 'newest', 'oldest', 'name_az', 'name_za', 'club_name'")

# Account Deletion Models
class AccountDeletionRequest(BaseModel):
    """Request model for account deletion"""
    deletion_type: str = Field(..., description="Type of deletion: 'temporary' or 'permanent'")
    reason: Optional[str] = Field(None, description="Optional reason for deletion")

class AccountDeletionResponse(BaseModel):
    """Response model for account deletion"""
    success: bool
    message: str
    deletion_type: Optional[str] = None
    user_id: Optional[str] = None
    usage_stats: Optional[Dict] = None
    clubs_affected: Optional[List[Dict]] = None
    deleted_at: Optional[str] = None
    error: Optional[str] = None

class AccountReactivationResponse(BaseModel):
    """Response model for account reactivation"""
    success: bool
    message: str
    user_id: Optional[str] = None
    clubs_reactivated: Optional[List[Dict]] = None
    reactivated_at: Optional[str] = None
    error: Optional[str] = None

class AccountDeletionStatusResponse(BaseModel):
    """Response model for account deletion status"""
    success: bool
    message: str
    user_id: str
    status: str
    membership_status: str
    deletion_type: Optional[str] = None
    deleted_at: Optional[str] = None
    deletion_reason: Optional[str] = None
    usage_stats: Optional[Dict] = None
    can_reactivate: bool = False
    error: Optional[str] = None

# Member Details API Models
class ClubMembershipInfo(BaseModel):
    """Individual club membership information"""
    club_id: str
    club_name: str
    club_name_based_id: Optional[str] = None
    captain_name: Optional[str] = None
    membership_type: str  # "trial" or "paid"
    membership_status: str  # "active", "inactive", "upcoming"
    pricing_plan: str  # "trial", "daily", "weekly", "monthly", "yearly"
    join_date: str
    end_date: Optional[str] = None
    amount_paid: Optional[float] = None
    payment_id: Optional[str] = None
    is_active: bool = True
    is_trial: bool = False
    created_at: str
    updated_at: str
    status: Optional[str] = None  # "upcoming", "active" for plan changes
    previous_plan: Optional[str] = None  # For plan changes
    is_upgraded: Optional[bool] = None  # For plan changes

class CaptainClubInfo(BaseModel):
    """Captain's club information"""
    club_id: str
    club_name: str
    club_name_based_id: Optional[str] = None
    club_status: str  # "approved", "pending", "rejected", etc.
    created_at: str
    member_count: Optional[int] = 0
    paid_member_count: Optional[int] = 0
    
    # Member-specific fields (when used in club_info context)
    membership_status: Optional[str] = None  # Member's status in this club
    membership_type: Optional[str] = None  # "trial" or "paid"
    pricing_plan: Optional[str] = None  # "trial", "daily", "weekly", etc.
    join_date: Optional[str] = None
    end_date: Optional[str] = None
    amount_paid: Optional[float] = None
    payment_id: Optional[str] = None

class MemberDetailsResponse(BaseModel):
    """Response model for member details API"""
    member_id: str
    full_name: str
    email: str
    phone: Optional[str] = None
    user_status: str  # "active", "inactive", "deleted"
    membership_status: str  # "active", "inactive", "trial", "deleted"
    profile_created_at: str
    
    # Specific club information (if club_id provided)
    club_info: Optional[CaptainClubInfo] = None
    member_club_status: Optional[str] = None  # Member's status in the specific club
    
    # Member's joined clubs
    joined_clubs: List[ClubMembershipInfo]
    total_clubs_joined: int
    active_clubs_count: int
    inactive_clubs_count: int
    upcoming_clubs_count: int
    trial_clubs_count: int
    paid_clubs_count: int
    
    # Captain's clubs (clubs created by the requesting captain)
    captain_clubs: List[CaptainClubInfo]
    total_captain_clubs: int
    
    # Payment summary
    total_amount_paid: float
    total_payments_count: int
    
    retrieved_at: str

# Member Deletion API Models
class MemberDeletionRequest(BaseModel):
    """Request model for deleting a member from a club"""
    club_id: str
    member_id: str
    deletion_type: Literal["temporary", "permanent"]
    reason: Optional[str] = None

class MemberDeletionResponse(BaseModel):
    """Response model for member deletion"""
    success: bool
    message: str
    deletion_type: str
    member_id: str
    club_id: str
    club_name: str
    member_name: str
    member_email: str
    deletion_date: str
    reason: Optional[str] = None
    
    # For temporary deletion
    reactivation_available: Optional[bool] = None
    usage_stats: Optional[Dict] = None
    
    # For permanent deletion
    refund_processed: Optional[bool] = None
    refund_amount: Optional[float] = None
    stripe_subscription_cancelled: Optional[bool] = None
    
    # Stripe management
    stripe_subscription_id: Optional[str] = None
    billing_paused: Optional[bool] = None
    next_billing_date: Optional[str] = None

class MemberReactivationRequest(BaseModel):
    """Request model for reactivating a temporarily deleted member"""
    club_id: str
    member_id: str

class MemberReactivationResponse(BaseModel):
    """Response model for member reactivation"""
    success: bool
    message: str
    member_id: str
    club_id: str
    club_name: str
    member_name: str
    reactivation_date: str
    billing_resumed: bool
    next_billing_date: Optional[str] = None
    unused_days_applied: Optional[int] = None


# ============================================================================
# VIEW PROFILE API MODELS
# ============================================================================

class ViewProfileBase(BaseModel):
    """Base model for view profile response"""
    first_name: str
    last_name: str
    email: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    role: str
    signup_date: str


class CaptainViewProfileResponse(ViewProfileBase):
    """Response model for captain view profile"""
    total_clubs_created_count: int
    total_moderators_count: int
    total_picks_submitted_count: int


class ModeratorViewProfileResponse(ViewProfileBase):
    """Response model for moderator view profile"""
    total_clubs_moderated_count: int
    total_picks_submitted_count: int


class MemberViewProfileResponse(ViewProfileBase):
    """Response model for member view profile"""
    total_clubs_joined_count: int


class ViewProfileResponse(BaseModel):
    """Union response model for view profile"""
    success: bool
    message: str
    data: Union[CaptainViewProfileResponse, ModeratorViewProfileResponse, MemberViewProfileResponse]