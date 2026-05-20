from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import re

class Admin(BaseModel):
    email: EmailStr
    password_hash: str

class AdminIn(BaseModel):
    email: EmailStr
    password: str

    @validator("password")
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain an uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain a number")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain a special character")
        return v

class AdminResponse(BaseModel):
    """Response model for admin data"""
    email: str
    name: str
    avatar_url: Optional[str] = None
    role: str = "Admin"

class TokenData(BaseModel):
    email: Optional[str] = None

# User Status Enum
class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"
    DELETED = "deleted"

# User Role Enum
class UserRole(str, Enum):
    MEMBER = "Member"
    MODERATOR = "Moderator"
    CAPTAIN = "Captain"
    ADMIN = "Admin"

# Sort Order Enum
class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"

# Sort Field Enum
class SortField(str, Enum):
    NAME = "name"
    DATE_JOINED = "date_joined"
    EMAIL = "email"
    STATUS = "status"

# User List Request Model
class UserListRequest(BaseModel):
    search: Optional[str] = None
    status: Optional[UserStatus] = None
    role: Optional[UserRole] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    sort_by: Optional[SortField] = SortField.DATE_JOINED
    sort_order: Optional[SortOrder] = SortOrder.DESC
    page: int = Field(1, ge=1)
    limit: int = Field(10, ge=1, le=10000)  # Increased limit to support CSV export



# User Search Request Model
class UserSearchRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full name of the user")
    email: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full email of the user")
    status: Optional[UserStatus] = Field(None, description="Filter by status: active, inactive, banned")
    date_from: Optional[datetime] = Field(None, description="Filter users joined on/after this date")
    date_to: Optional[datetime] = Field(None, description="Filter users joined on/before this date")
    page: int = Field(1, ge=1, description="Page number (default: 1)")
    limit: int = Field(20, ge=1, le=100, description="Items per page (default: 20)")
    sort_by: Optional[SortField] = Field(SortField.DATE_JOINED, description="Field to sort by: name, date_joined, email, status")
    sort_order: Optional[SortOrder] = Field(SortOrder.DESC, description="Sort order: asc or desc")

    @validator('name')
    def validate_name(cls, v):
        if v:
            # Remove extra spaces and validate format
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z\s]+$', v):
                raise ValueError('Name must contain only letters and spaces')
        return v

    @validator('email')
    def validate_email(cls, v):
        if v:
            # Basic email format validation
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
                raise ValueError('Invalid email format')
        return v

    @validator('date_to')
    def validate_date_range(cls, v, values):
        if v and 'date_from' in values and values['date_from']:
            if v < values['date_from']:
                raise ValueError('date_to must be after date_from')
        return v

# User Export Request Model
class UserExportRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full name of the user")
    email: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full email of the user")
    status: Optional[UserStatus] = Field(None, description="Filter by status: active, inactive, banned")
    role: Optional[UserRole] = Field(None, description="Filter by role: Captain or Member")
    date_from: Optional[datetime] = Field(None, description="Filter users joined on/after this date")
    date_to: Optional[datetime] = Field(None, description="Filter users joined on/before this date")
    sort_by: Optional[SortField] = Field(SortField.DATE_JOINED, description="Field to sort by: name, date_joined, email, status")
    sort_order: Optional[SortOrder] = Field(SortOrder.DESC, description="Sort order: asc or desc")
    include_deleted: bool = Field(False, description="Include deleted users in export")
    fields: Optional[List[str]] = Field(None, description="Specific fields to include in export")

    @validator('name')
    def validate_name(cls, v):
        if v:
            # Remove extra spaces and validate format
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z\s]+$', v):
                raise ValueError('Name must contain only letters and spaces')
        return v

    @validator('email')
    def validate_email(cls, v):
        if v:
            # Basic email format validation
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
                raise ValueError('Invalid email format')
        return v

    @validator('date_to')
    def validate_date_range(cls, v, values):
        if v and 'date_from' in values and values['date_from']:
            if v < values['date_from']:
                raise ValueError('date_to must be after date_from')
        return v

    @validator('fields')
    def validate_fields(cls, v):
        if v:
            valid_fields = [
                'user_id', 'full_name', 'email', 'phone', 'role', 'status',
                'date_joined', 'last_login', 'is_verified', 'membership_count',
                'total_clubs', 'is_deleted', 'deleted_at'
            ]
            invalid_fields = [field for field in v if field not in valid_fields]
            if invalid_fields:
                raise ValueError(f'Invalid fields: {invalid_fields}. Valid fields are: {valid_fields}')
        return v

# Add User Request Model
class AddUserRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Full name of the user")
    email: EmailStr = Field(..., description="Must be unique")
    phone: Optional[str] = Field(None, min_length=10, max_length=15, description="Phone number")
    status: UserStatus = Field(UserStatus.ACTIVE, description="User status")
    role: UserRole = Field(UserRole.MEMBER, description="User role")
    password: str = Field(..., min_length=8, description="Password for new user")

    @validator('name')
    def name_no_special_chars(cls, v):
        if not re.match(r'^[A-Za-z\s]+$', v):
            raise ValueError('Name must contain only letters and spaces')
        return v

    @validator('phone')
    def phone_numeric(cls, v):
        if v and not v.isdigit():
            raise ValueError('Phone number must be numeric')
        return v

    @validator('password')
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r'[A-Z]', v):
            raise ValueError("Password must contain an uppercase letter")
        if not re.search(r'[a-z]', v):
            raise ValueError("Password must contain a lowercase letter")
        if not re.search(r'\d', v):
            raise ValueError("Password must contain a number")
        if not re.search(r'[^A-Za-z0-9]', v):
            raise ValueError("Password must contain a special character")
        return v

# Edit User Request Model
class EditUserRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Full name of the user")
    email: Optional[EmailStr] = Field(None, description="Must be unique")
    phone: Optional[str] = Field(None, min_length=10, max_length=15, description="Phone number")
    status: Optional[UserStatus] = Field(None, description="User status")
    role: Optional[UserRole] = Field(None, description="User role")

    @validator('name')
    def name_no_special_chars(cls, v):
        if v and not re.match(r'^[A-Za-z\s]+$', v):
            raise ValueError('Name must contain only letters and spaces')
        return v

    @validator('phone')
    def phone_numeric(cls, v):
        if v and not v.isdigit():
            raise ValueError('Phone number must be numeric')
        return v

class ImageUploadResponse(BaseModel):
    """Response model for image upload"""
    success: bool
    message: str
    image_url: str
    image_id: str
    filename: str
    file_size: int
    content_type: str
    upload_timestamp: datetime
    metadata: Optional[dict] = None

# User Response Model
class UserResponse(BaseModel):
    user_id: str
    full_name: str
    email: str
    phone: str
    role: str
    status: str
    date_joined: datetime
    last_login: Optional[datetime] = None
    profile_picture: Optional[str] = None
    is_verified: bool = False
    membership_count: int = 0
    total_clubs: int = 0
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    is_deleted_per_admin: bool = False
    is_deleted_temp_admin: bool = False
    membership_status: Optional[str] = None
    membership_type: Optional[str] = None
    subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    plan_details: Optional[List[dict]] = None
    club_memberships: Optional[List[dict]] = None

# Pagination Metadata Model
class PaginationMetadata(BaseModel):
    total_users: int
    current_page: int
    total_pages: int
    has_next: bool
    has_prev: bool
    limit: int

# User List Response Model
class UserListResponse(BaseModel):
    success: bool
    message: str
    users: List[UserResponse]
    pagination: PaginationMetadata

# User Search Response Model
class UserSearchResponse(BaseModel):
    success: bool
    message: str
    users: List[UserResponse]
    pagination: PaginationMetadata
    search_metadata: dict

# User Export Response Model
class UserExportResponse(BaseModel):
    success: bool
    message: str
    download_url: Optional[str] = None
    filename: Optional[str] = None
    csv_content: Optional[str] = None  # The actual CSV data as string
    total_records: int = 0
    export_metadata: dict

# Audit Log Model
class AuditLog(BaseModel):
    action: str  # "create", "update", "delete"
    admin_email: str
    user_id: str
    changes: Optional[dict] = None
    timestamp: datetime
    ip_address: Optional[str] = None

# Search Log Model
class SearchLog(BaseModel):
    admin_email: str
    search_criteria: dict
    results_count: int
    timestamp: datetime
    ip_address: Optional[str] = None
    response_time_ms: int

# Export Log Model
class ExportLog(BaseModel):
    admin_email: str
    export_criteria: dict
    total_records: int
    filename: str
    timestamp: datetime
    ip_address: Optional[str] = None
    file_size_bytes: int

# API Response Models
class AddUserResponse(BaseModel):
    success: bool
    message: str
    user_id: Optional[str] = None
    user: Optional[UserResponse] = None
    error: Optional[str] = None

class EditUserResponse(BaseModel):
    success: bool
    message: str
    user_id: str
    user: Optional[UserResponse] = None
    changes: Optional[dict] = None
    error: Optional[str] = None

class DeleteUserResponse(BaseModel):
    success: bool
    message: str
    user_id: str
    error: Optional[str] = None

# Club Status Enum
class ClubStatus(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    INACTIVE = "inactive"
    DELETED = "deleted"
   



# Club Sort Field Enum
class ClubSortField(str, Enum):
    NAME = "name"
    OWNER = "owner"
    CREATED_DATE = "created_date"
    MODERATOR_COUNT = "moderator_count"
    SUBSCRIPTION_PRICE = "subscription_price"
    STATUS = "status"

# Club List Request Model
class ClubListRequest(BaseModel):
    search: Optional[str] = Field(None, description="Search by club name or owner name")
    status: Optional[ClubStatus] = Field(None, description="Filter by club status")
    date_from: Optional[datetime] = Field(None, description="Filter clubs created on/after this date")
    date_to: Optional[datetime] = Field(None, description="Filter clubs created on/before this date")
    sort_by: Optional[ClubSortField] = Field(ClubSortField.CREATED_DATE, description="Field to sort by")
    sort_order: Optional[SortOrder] = Field(SortOrder.DESC, description="Sort order: asc or desc")
    page: int = Field(1, ge=1, description="Page number")
    limit: int = Field(10, ge=1, le=100, description="Items per page")

    @validator('date_to')
    def validate_date_range(cls, v, values):
        if v and 'date_from' in values and values['date_from']:
            if v < values['date_from']:
                raise ValueError('date_to must be after date_from')
        return v

# Club Response Model
class ClubResponse(BaseModel):
    club_id: str
    name: str
    description: str
    owner_name: str
    owner_id: str
    moderator_count: int
    subscription_price: float
    currency: str
    status: str
    logo_url: Optional[str] = None
    created_date: datetime
    updated_date: datetime
    member_count: int
    win_percentage: float
    is_active: bool

# Club Pagination Metadata
class ClubPaginationMetadata(BaseModel):
    total_clubs: int
    current_page: int
    total_pages: int
    has_next: bool
    has_prev: bool
    limit: int

# Club List Response
class ClubListResponse(BaseModel):
    success: bool
    message: str
    clubs: List[ClubResponse]
    pagination: ClubPaginationMetadata

# Club Statistics Response
class ClubStatisticsResponse(BaseModel):
    success: bool
    message: str
    statistics: dict

# Club Search Request Model
class ClubSearchRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full club name")
    owner_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full owner name")
    status: Optional[ClubStatus] = Field(None, description="Filter by status: approved, pending, rejected")
    date_from: Optional[datetime] = Field(None, description="Filter clubs created on/after this date")
    date_to: Optional[datetime] = Field(None, description="Filter clubs created on/before this date")
    page: int = Field(1, ge=1, description="Page number (default: 1)")
    limit: int = Field(20, ge=1, le=100, description="Items per page (default: 20)")
    sort_by: Optional[ClubSortField] = Field(ClubSortField.CREATED_DATE, description="Field to sort by: name, owner, created_date, moderator_count, subscription_price, status")
    sort_order: Optional[SortOrder] = Field(SortOrder.DESC, description="Sort order: asc or desc")

    @validator('name')
    def validate_name(cls, v):
        if v:
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z0-9\s\-_&]+$', v):
                raise ValueError('Club name must contain only letters, numbers, spaces, hyphens, underscores, and ampersands')
        return v

    @validator('owner_name')
    def validate_owner_name(cls, v):
        if v:
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z\s]+$', v):
                raise ValueError('Owner name must contain only letters and spaces')
        return v

    @validator('date_to')
    def validate_date_range(cls, v, values):
        if v and 'date_from' in values and values['date_from']:
            if v < values['date_from']:
                raise ValueError('date_to must be after date_from')
        return v

# Club Search Response Model
class ClubSearchResponse(BaseModel):
    success: bool
    message: str
    clubs: List[ClubResponse]
    pagination: ClubPaginationMetadata
    search_metadata: dict

# Club Export Request Model
class ClubExportRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full club name")
    owner_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full owner name")
    status: Optional[ClubStatus] = Field(None, description="Filter by status: approved, pending, rejected")
    date_from: Optional[datetime] = Field(None, description="Filter clubs created on/after this date")
    date_to: Optional[datetime] = Field(None, description="Filter clubs created on/before this date")
    sort_by: Optional[ClubSortField] = Field(ClubSortField.CREATED_DATE, description="Field to sort by: name, owner, created_date, moderator_count, subscription_price, status")
    sort_order: Optional[SortOrder] = Field(SortOrder.DESC, description="Sort order: asc or desc")
    include_inactive: bool = Field(False, description="Include inactive clubs in export")
    fields: Optional[List[str]] = Field(None, description="Specific fields to include in export")

    @validator('name')
    def validate_name(cls, v):
        if v:
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z0-9\s\-_&]+$', v):
                raise ValueError('Club name must contain only letters, numbers, spaces, hyphens, underscores, and ampersands')
        return v

    @validator('owner_name')
    def validate_owner_name(cls, v):
        if v:
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z\s]+$', v):
                raise ValueError('Owner name must contain only letters and spaces')
        return v

    @validator('date_to')
    def validate_date_range(cls, v, values):
        if v and 'date_from' in values and values['date_from']:
            if v < values['date_from']:
                raise ValueError('date_to must be after date_from')
        return v

    @validator('fields')
    def validate_fields(cls, v):
        if v:
            valid_fields = [
                'club_id', 'name', 'description', 'category', 'owner_name', 'owner_id',
                'moderator_count', 'subscription_price', 'currency', 'status', 'logo_url',
                'created_date', 'updated_date', 'member_count', 'win_percentage', 'is_active'
            ]
            invalid_fields = [field for field in v if field not in valid_fields]
            if invalid_fields:
                raise ValueError(f'Invalid fields: {invalid_fields}. Valid fields are: {valid_fields}')
        return v

# Club Export Response Model
class ClubExportResponse(BaseModel):
    success: bool
    message: str
    download_url: Optional[str] = None
    filename: Optional[str] = None
    total_records: int = 0
    export_metadata: dict

# Club Search Log Model
class ClubSearchLog(BaseModel):
    admin_email: str
    search_criteria: dict
    results_count: int
    timestamp: datetime
    ip_address: Optional[str] = None
    response_time_ms: int

# Club Export Log Model
class ClubExportLog(BaseModel):
    admin_email: str
    export_criteria: dict
    total_records: int
    filename: str
    timestamp: datetime
    ip_address: Optional[str] = None
    file_size_bytes: int

# Club Action Enum
class ClubAction(str, Enum):
    BAN = "ban"
    SUSPEND = "suspend"
    REACTIVATE = "reactivate"

# Club Plan Type Enum
class ClubPlanType(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    TRIAL = "trial"

# Moderator Role Enum
class ModeratorRole(str, Enum):
    MODERATOR = "moderator"
    ANALYST = "analyst"
    EDITOR = "editor"

# Club Status Update Request
class ClubStatusUpdateRequest(BaseModel):
    action: ClubAction = Field(..., description="Action to perform: ban, suspend, or reactivate")
    reason: Optional[str] = Field(None, min_length=10, max_length=500, description="Reason for the action")
    duration_days: Optional[int] = Field(None, ge=1, le=365, description="Duration in days for suspension")

    @validator('reason')
    def validate_reason(cls, v):
        if v:
            v = v.strip()
            if len(v) < 10:
                raise ValueError('Reason must be at least 10 characters long')
        return v

# Moderator Details Model
class ModeratorDetails(BaseModel):
    user_id: str
    name: str
    email: str
    phone: Optional[str] = None
    role: ModeratorRole
    joined_date: datetime
    is_active: bool = True
    avatar_url: Optional[str] = None

# Owner Details Model
class OwnerDetails(BaseModel):
    user_id: str
    name: str
    email: str
    phone: Optional[str] = None
    active_club_count: int
    revenue_earned: float
    total_revenue: float
    avatar_url: Optional[str] = None
    joined_date: datetime
    is_verified: bool = False

# Financial Details Model
class FinancialDetails(BaseModel):
    total_revenue: float
    active_subscribers: int
    past_subscriptions: int
    monthly_recurring_revenue: float
    average_subscription_value: float
    refund_total: float
    net_revenue: float

# Refund Log Entry
class RefundLogEntry(BaseModel):
    refund_id: str
    amount: float
    date: datetime
    reason: str
    member_name: str
    member_email: str
    processed_by: str

# Payment History Entry
class PaymentHistoryEntry(BaseModel):
    transaction_id: str
    member_name: str
    member_email: str
    amount: float
    date: datetime
    status: str
    payment_method: Optional[str] = None
    subscription_plan: str

# Activity Metrics
class ActivityMetrics(BaseModel):
    picks_posted: int
    messages_sent: int
    total_engagement: int
    last_activity_date: Optional[datetime] = None
    days_since_last_activity: int
    is_inactive: bool
    engagement_score: float  # 0-100 scale

# Daily/Weekly Engagement Breakdown
class EngagementBreakdown(BaseModel):
    period: str  # "daily" or "weekly"
    data: List[Dict[str, Any]]  # Flexible structure for time-series data

# Pick Details Model
class PickDetails(BaseModel):
    pick_id: str
    submitted_by: str
    submitter_role: str
    submitter_name: str
    game_info: str
    pick_type: str
    pick_details: str
    timestamp: datetime
    status: str
    outcome: Optional[str] = None
    win_loss: Optional[bool] = None

# Club Details Response Model
class ClubDetailsResponse(BaseModel):
    success: bool
    message: str
    club: Dict[str, Any]  # Complete club information
    owner: OwnerDetails
    moderators: List[ModeratorDetails]
    financials: FinancialDetails
    activity: ActivityMetrics
    engagement_breakdown: Optional[EngagementBreakdown] = None
    picks: List[PickDetails]
    refund_log: List[RefundLogEntry]
    payment_history: List[PaymentHistoryEntry]

# Club Status Update Response
class ClubStatusUpdateResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    previous_status: str
    new_status: str
    action_taken: str
    reason: Optional[str] = None
    effective_date: datetime
    expires_date: Optional[datetime] = None
    admin_email: str

# Club Analytics Request
class ClubAnalyticsRequest(BaseModel):
    date_from: Optional[datetime] = Field(None, description="Start date for analytics")
    date_to: Optional[datetime] = Field(None, description="End date for analytics")
    include_financials: bool = Field(True, description="Include financial data")
    include_activity: bool = Field(True, description="Include activity metrics")
    include_picks: bool = Field(True, description="Include pick history")

# Club Analytics Response
class ClubAnalyticsResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    analytics_period: str
    financial_summary: Optional[Dict[str, Any]] = None
    activity_summary: Optional[Dict[str, Any]] = None
    picks_summary: Optional[Dict[str, Any]] = None
    generated_at: datetime

# Club Search and Filter Request
class ClubAdvancedSearchRequest(BaseModel):
    name: Optional[str] = Field(None, description="Club name search")
    owner_name: Optional[str] = Field(None, description="Owner name search")
    status: Optional[ClubStatus] = Field(None, description="Club status filter")
    min_revenue: Optional[float] = Field(None, ge=0, description="Minimum revenue filter")
    max_revenue: Optional[float] = Field(None, ge=0, description="Maximum revenue filter")
    is_inactive: Optional[bool] = Field(None, description="Filter by inactivity")
    min_members: Optional[int] = Field(None, ge=0, description="Minimum member count")
    date_from: Optional[datetime] = Field(None, description="Created date from")
    date_to: Optional[datetime] = Field(None, description="Created date to")
    sort_by: Optional[ClubSortField] = Field(ClubSortField.CREATED_DATE, description="Sort field")
    sort_order: Optional[SortOrder] = Field(SortOrder.DESC, description="Sort order")
    page: int = Field(1, ge=1, description="Page number")
    limit: int = Field(20, ge=1, le=100, description="Items per page")

    @validator('min_revenue', 'max_revenue')
    def validate_revenue_range(cls, v, values):
        if v is not None:
            if v < 0:
                raise ValueError('Revenue values must be non-negative')
        return v

    @validator('max_revenue')
    def validate_max_revenue(cls, v, values):
        if v is not None and 'min_revenue' in values and values['min_revenue'] is not None:
            if v < values['min_revenue']:
                raise ValueError('max_revenue must be greater than or equal to min_revenue')
        return v

# Club Advanced Search Response
class ClubAdvancedSearchResponse(BaseModel):
    success: bool
    message: str
    clubs: List[Dict[str, Any]]  # Enhanced club data
    pagination: ClubPaginationMetadata
    search_metadata: dict
    analytics_summary: Optional[Dict[str, Any]] = None

# Club Bulk Action Request
class ClubBulkActionRequest(BaseModel):
    club_ids: List[str] = Field(..., min_items=1, max_items=100, description="List of club IDs")
    action: ClubAction = Field(..., description="Action to perform on all clubs")
    reason: Optional[str] = Field(None, min_length=10, max_length=500, description="Reason for bulk action")
    duration_days: Optional[int] = Field(None, ge=1, le=365, description="Duration for suspensions")

    @validator('club_ids')
    def validate_club_ids(cls, v):
        if not v:
            raise ValueError('At least one club ID must be provided')
        if len(v) > 100:
            raise ValueError('Maximum 100 clubs can be processed in one request')
        return v

# Club Bulk Action Response
class ClubBulkActionResponse(BaseModel):
    success: bool
    message: str
    action: str
    total_clubs: int
    processed_clubs: int
    failed_clubs: int
    results: List[Dict[str, Any]]  # Individual results for each club
    summary: Dict[str, Any]  # Overall summary of the bulk operation

# Club Export Request (Enhanced)
class ClubExportRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Club name filter")
    owner_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Owner name filter")
    status: Optional[ClubStatus] = Field(None, description="Status filter")
    min_revenue: Optional[float] = Field(None, ge=0, description="Minimum revenue")
    max_revenue: Optional[float] = Field(None, ge=0, description="Maximum revenue")
    is_inactive: Optional[bool] = Field(None, description="Inactivity filter")
    date_from: Optional[datetime] = Field(None, description="Created date from")
    date_to: Optional[datetime] = Field(None, description="Created date to")
    sort_by: Optional[ClubSortField] = Field(ClubSortField.CREATED_DATE, description="Sort field")
    sort_order: Optional[SortOrder] = Field(SortOrder.DESC, description="Sort order")
    include_financials: bool = Field(True, description="Include financial data in export")
    include_activity: bool = Field(True, description="Include activity metrics in export")
    include_moderators: bool = Field(True, description="Include moderator details in export")
    fields: Optional[List[str]] = Field(None, description="Specific fields to include")

    @validator('fields')
    def validate_fields(cls, v):
        if v:
            valid_fields = [
                'club_id', 'name', 'description', 'owner_name', 'owner_email', 'owner_phone',
                'moderator_count', 'subscription_price', 'currency', 'status', 'logo_url', 'created_date',
                'updated_date', 'member_count', 'win_percentage', 'is_active', 'total_revenue',
                'active_subscribers', 'picks_posted', 'messages_sent', 'engagement_score', 'is_inactive'
            ]
            invalid_fields = [field for field in v if field not in valid_fields]
            if invalid_fields:
                raise ValueError(f'Invalid fields: {invalid_fields}. Valid fields are: {valid_fields}')
        return v

# Club Export Response (Enhanced)
class ClubExportResponse(BaseModel):
    success: bool
    message: str
    download_url: Optional[str] = None
    filename: Optional[str] = None
    total_records: int = 0
    export_metadata: dict
    export_summary: Optional[Dict[str, Any]] = None

# Club Activity Log Entry
class ClubActivityLogEntry(BaseModel):
    log_id: str
    club_id: str
    action: str
    performed_by: str
    admin_email: str
    details: Dict[str, Any]
    timestamp: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

# Club Activity Log Response
class ClubActivityLogResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    total_logs: int
    logs: List[ClubActivityLogEntry]
    pagination: ClubPaginationMetadata

# Club Performance Metrics
class ClubPerformanceMetrics(BaseModel):
    club_id: str
    win_rate: float
    total_picks: int
    winning_picks: int
    losing_picks: int
    average_odds: float
    total_stake: float
    total_return: float
    profit_loss: float
    roi_percentage: float
    monthly_performance: List[Dict[str, Any]]
    top_performers: List[Dict[str, Any]]

# Club Performance Response
class ClubPerformanceResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    performance: ClubPerformanceMetrics
    generated_at: datetime

# Club Type Enum
class ClubType(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"

# Club Owner Create Model
class ClubOwnerCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Owner's full name")
    email: EmailStr = Field(..., description="Owner's email address (must be unique)")
    phone: str = Field(..., min_length=10, max_length=15, description="Owner's phone number")
    password: str = Field(..., min_length=8, description="Owner's password")

    @validator('name')
    def validate_name(cls, v):
        v = ' '.join(v.split())  # Remove extra spaces
        if not re.match(r'^[A-Za-z\s]+$', v):
            raise ValueError('Name must contain only letters and spaces')
        return v

    @validator('phone')
    def validate_phone(cls, v):
        # Remove non-numeric characters
        cleaned_phone = re.sub(r'[^\d]', '', v)
        if len(cleaned_phone) < 10 or len(cleaned_phone) > 15:
            raise ValueError('Phone number must be between 10-15 digits')
        return cleaned_phone

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r'[A-Z]', v):
            raise ValueError("Password must contain an uppercase letter")
        if not re.search(r'[a-z]', v):
            raise ValueError("Password must contain a lowercase letter")
        if not re.search(r'\d', v):
            raise ValueError("Password must contain a number")
        if not re.search(r'[^A-Za-z0-9]', v):
            raise ValueError("Password must contain a special character")
        return v

# Club Owner Update Model
class ClubOwnerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100, description="Owner's full name")
    email: Optional[EmailStr] = Field(None, description="Owner's email address (must be unique)")
    phone: Optional[str] = Field(None, min_length=10, max_length=15, description="Owner's phone number")
    password: Optional[str] = Field(None, min_length=8, description="Owner's new password (optional)")

    @validator('name')
    def validate_name(cls, v):
        if v:
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z\s]+$', v):
                raise ValueError('Name must contain only letters and spaces')
        return v

    @validator('phone')
    def validate_phone(cls, v):
        if v:
            cleaned_phone = re.sub(r'[^\d]', '', v)
            if len(cleaned_phone) < 10 or len(cleaned_phone) > 15:
                raise ValueError('Phone number must be between 10-15 digits')
            return cleaned_phone
        return v

    @validator('password')
    def validate_password(cls, v):
        if v:
            if len(v) < 8:
                raise ValueError("Password must be at least 8 characters")
            if not re.search(r'[A-Z]', v):
                raise ValueError("Password must contain an uppercase letter")
            if not re.search(r'[a-z]', v):
                raise ValueError("Password must contain a lowercase letter")
            if not re.search(r'\d', v):
                raise ValueError("Password must contain a number")
            if not re.search(r'[^A-Za-z0-9]', v):
                raise ValueError("Password must contain a special character")
        return v

# Club Create Request Model
class ClubCreateRequest(BaseModel):
    club_name: str = Field(..., min_length=2, max_length=100, description="Club name (must be unique)")
    description: str = Field(..., min_length=10, max_length=1000, description="Club description")
    club_type: ClubType = Field(..., description="Club type: public or private")
    logo: Optional[str] = Field(None, description="URL to club logo")
    status: ClubStatus = Field(ClubStatus.PENDING, description="Club status")
    owner: ClubOwnerCreate = Field(..., description="Club owner details")

    @validator('club_name')
    def validate_club_name(cls, v):
        v = ' '.join(v.split())  # Remove extra spaces
        if not re.match(r'^[A-Za-z0-9\s\-_&]+$', v):
            raise ValueError('Club name must contain only letters, numbers, spaces, hyphens, underscores, and ampersands')
        return v

    @validator('logo')
    def validate_logo(cls, v):
        if v:
            # Basic URL validation
            if not re.match(r'^https?://.+\.(jpg|jpeg|png|gif|webp)$', v, re.IGNORECASE):
                raise ValueError('Logo must be a valid image URL (jpg, jpeg, png, gif, webp)')
        return v

# Club Update Request Model
class ClubUpdateRequest(BaseModel):
    club_name: Optional[str] = Field(None, min_length=2, max_length=100, description="Club name (must be unique)")
    description: Optional[str] = Field(None, min_length=10, max_length=1000, description="Club description")
    club_type: Optional[ClubType] = Field(None, description="Club type: public or private")
    logo: Optional[str] = Field(None, description="URL to club logo")
    status: Optional[ClubStatus] = Field(None, description="Club status")
    owner: Optional[ClubOwnerUpdate] = Field(None, description="Club owner details (optional)")

    @validator('club_name')
    def validate_club_name(cls, v):
        if v:
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z0-9\s\-_&]+$', v):
                raise ValueError('Club name must contain only letters, numbers, spaces, hyphens, underscores, and ampersands')
        return v

    @validator('logo')
    def validate_logo(cls, v):
        if v:
            if not re.match(r'^https?://.+\.(jpg|jpeg|png|gif|webp)$', v, re.IGNORECASE):
                raise ValueError('Logo must be a valid image URL (jpg, jpeg, png, gif, webp)')
        return v

# Club Create Response Model
class ClubCreateResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    owner_id: str
    club: Dict[str, Any]
    owner: Dict[str, Any]
    created_at: datetime

# Club Update Response Model
class ClubUpdateResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    owner_id: Optional[str] = None
    club: Dict[str, Any]
    owner: Optional[Dict[str, Any]] = None
    updated_at: datetime
    changes: Dict[str, Any]

# Club Delete Response Model
class ClubDeleteResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    owner_id: Optional[str] = None
    deleted_at: datetime
    cascade_deleted: bool = False

# Club Update Details Request Model
class ClubUpdateDetailsRequest(BaseModel):
    logo_url: Optional[str] = Field(None, description="Club logo URL")
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Club name")
    sub_description: Optional[str] = Field(None, max_length=200, description="Short description/tagline")
    description: Optional[str] = Field(None, max_length=1000, description="Full club description")
    status: Optional[ClubStatus] = Field(None, description="Club status: pending, approved, rejected")
    owner_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Owner's full name")

    @validator('name')
    def validate_name(cls, v):
        if v is not None:
            # Remove extra spaces and validate format
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z0-9\s\-_&]+$', v):
                raise ValueError('Club name must contain only letters, numbers, spaces, hyphens, underscores, and ampersands')
        return v

    @validator('logo_url')
    def validate_logo_url(cls, v):
        if v is not None and v != "":
            # Basic URL validation
            if not re.match(r'^https?://.+', v):
                raise ValueError('Logo URL must be a valid HTTP/HTTPS URL')
        return v

# Audit Log Entry Model
class ClubAuditLogEntry(BaseModel):
    log_id: str
    action: str  # CREATE, UPDATE, DELETE
    admin_email: str
    club_id: Optional[str] = None
    owner_id: Optional[str] = None
    changes: Optional[Dict[str, Any]] = None
    timestamp: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

# Enhanced Club Search and Filter Sort Fields
class ClubSearchSortField(str, Enum):
    CLUB_NAME = "club_name"
    OWNER_NAME = "owner_name"
    DATE_CREATED = "date_created"
    SUBSCRIPTION_PRICE = "subscription_price"
    MODERATOR_COUNT = "moderator_count"
    STATUS = "status"

# ========================================
# Moderator List API Models
# ========================================

# Moderator Status Enum
class ModeratorStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

# Club Assignment Model for Moderator
class ModeratorClubAssignment(BaseModel):
    club_id: str
    club_name: str
    captain_name: str
    captain_email: Optional[str] = None
    role: ModeratorRole
    joined_date: str  # Formatted as DD MMM YYYY
    status: str  # active, inactive
    subscription_status: str  # active, cancelled, etc.

# Moderator List Item Model
class ModeratorListItem(BaseModel):
    moderator_id: str
    name: str
    email: str = "--"  # Default to "--" if missing
    phone: Optional[str] = None
    status: ModeratorStatus
    total_clubs: int
    clubs: List[ModeratorClubAssignment] = []
    last_active: Optional[str] = None  # Formatted date
    created_at: str  # Formatted as DD MMM YYYY
    avatar_url: Optional[str] = None

# Moderator Sort Field Enum
class ModeratorSortField(str, Enum):
    NAME = "name"
    DATE_JOINED = "date_joined"
    CLUB_COUNT = "club_count"
    EMAIL = "email"
    STATUS = "status"

# Sort Order Enum (reuse existing if available)
class ModeratorSortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"

# Enhanced Moderator List Request Model
class ModeratorListRequest(BaseModel):
    # Search and basic filters
    search: Optional[str] = Field(None, description="Search by moderator name, email, or captain name")
    status: Optional[ModeratorStatus] = Field(None, description="Filter by active/inactive status")
    club_id: Optional[str] = Field(None, description="Filter by assigned club ID")
    
    # Individual search filters (granular search control)
    name: Optional[str] = Field(None, description="Search by moderator name (partial match)")
    email: Optional[str] = Field(None, description="Search by moderator email (partial match)")
    
    # Enhanced filters
    club: Optional[str] = Field(None, description="Filter by club ID or name (partial match)")
    assigned_by: Optional[str] = Field(None, description="Filter by captain ID or name who assigned the moderator")
    
    # Sorting options
    sort_by: Optional[ModeratorSortField] = Field(ModeratorSortField.DATE_JOINED, description="Field to sort by")
    order: Optional[ModeratorSortOrder] = Field(ModeratorSortOrder.DESC, description="Sort order: asc or desc")
    
    # Pagination
    page: int = Field(1, ge=1, description="Page number for pagination")
    limit: int = Field(20, ge=1, le=100, description="Number of records per page")

    @validator('search')
    def validate_search(cls, v):
        if v:
            v = v.strip()
            if len(v) < 2:
                raise ValueError('Search term must be at least 2 characters')
        return v

    @validator('club_id')
    def validate_club_id(cls, v):
        if v:
            try:
                from bson import ObjectId
                ObjectId(v)
            except:
                raise ValueError('Invalid club ID format')
        return v
    
    @validator('club')
    def validate_club(cls, v):
        if v:
            v = v.strip()
            if len(v) < 1:
                raise ValueError('Club filter must not be empty')
        return v
    
    @validator('assigned_by')
    def validate_assigned_by(cls, v):
        if v:
            v = v.strip()
            if len(v) < 1:
                raise ValueError('Assigned by filter must not be empty')
        return v
    
    @validator('name')
    def validate_name(cls, v):
        if v:
            v = v.strip()
            if len(v) < 2:
                raise ValueError('Name search must be at least 2 characters')
        return v
    
    @validator('email')
    def validate_email(cls, v):
        if v:
            v = v.strip()
            if len(v) < 2:
                raise ValueError('Email search must be at least 2 characters')
        return v

# Moderator List Pagination Metadata
class ModeratorListPagination(BaseModel):
    current_page: int
    total_pages: int
    total_records: int
    records_per_page: int
    has_next: bool
    has_previous: bool

# Moderator List Response Model
class ModeratorListResponse(BaseModel):
    success: bool
    message: str
    data: List[ModeratorListItem]
    pagination: ModeratorListPagination
    filters_applied: Dict[str, Any]
    total_moderators: int
    active_moderators: int
    inactive_moderators: int
    response_time_ms: Optional[float] = None

# Moderator Search Log Model
class ModeratorSearchLog(BaseModel):
    search_id: str
    admin_email: str
    search_filters: Dict[str, Any]
    results_count: int
    response_time_ms: float
    timestamp: datetime
    ip_address: Optional[str] = None

# ========================================
# Club Approval/Rejection API Models
# ========================================

# Club Approval Status Enum
class ClubApprovalStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REJECTED_TEMPORARY = "rejected_temporary"
    REJECTED_PERMANENT = "rejected_permanent"
    PENDING = "pending"
    SUSPENDED = "suspended"

# Club Approval Request Model
class ClubApprovalRequest(BaseModel):
    status: ClubApprovalStatus
    reason: Optional[str] = Field(None, max_length=500, description="Reason for approval/rejection")
    notify_owner: bool = Field(True, description="Send email notification to club owner")
    admin_notes: Optional[str] = Field(None, max_length=1000, description="Internal admin notes")
    rejection_type: Optional[str] = Field(None, description="Type of rejection: 'temporary' or 'permanent'")
    refund_amount: Optional[float] = Field(None, description="Amount to refund for permanent rejection")

    @validator('reason')
    def validate_reason_for_rejection(cls, v, values):
        status = values.get('status')
        if status in [ClubApprovalStatus.REJECTED, ClubApprovalStatus.REJECTED_TEMPORARY, ClubApprovalStatus.REJECTED_PERMANENT] and not v:
            raise ValueError('Reason is required for rejection')
        return v

    @validator('rejection_type')
    def validate_rejection_type(cls, v, values):
        status = values.get('status')
        if status in [ClubApprovalStatus.REJECTED_TEMPORARY, ClubApprovalStatus.REJECTED_PERMANENT]:
            if not v or v not in ['temporary', 'permanent']:
                raise ValueError('rejection_type must be "temporary" or "permanent" for rejection status')
        return v

# Club Approval Response Model
class ClubApprovalResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    previous_status: str
    new_status: str
    notification_sent: bool
    owner_email: Optional[str] = None
    admin_email: str
    timestamp: datetime
    approval_id: str  # For tracking purposes
    rejection_type: Optional[str] = None  # 'temporary' or 'permanent'
    refund_amount: Optional[float] = None  # Amount refunded for permanent rejection
    is_resubmit: Optional[bool] = None  # Whether club can be resubmitted
    is_club_reject_permanently: Optional[bool] = None  # Whether club is permanently rejected
    is_club_reject_temporary: Optional[bool] = None  # Whether club is temporarily rejected

# ========================================
# Club Monitoring API Models
# ========================================

# Activity Period Enum
class ActivityPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"

# Club Activity Metrics Model
class ClubActivityMetrics(BaseModel):
    period: ActivityPeriod
    date_range: Dict[str, str]  # start_date, end_date
    messages_sent: int
    picks_posted: int
    new_members: int
    active_members: int
    engagement_rate: float  # Percentage
    avg_daily_messages: float
    avg_daily_picks: float
    last_activity_date: Optional[str] = None  # DD MMM YYYY format
    days_since_last_activity: int
    is_inactive: bool  # True if no activity in last 7 days

# Club Performance Summary Model
class ClubPerformanceSummary(BaseModel):
    total_picks: int
    winning_picks: int
    losing_picks: int
    pending_picks: int
    win_rate: float
    loss_rate: float
    roi: float  # Return on investment percentage
    profit_loss: float
    best_streak: int
    current_streak: int
    performance_trend: str  # "improving", "declining", "stable"

# Club Health Status Model
class ClubHealthStatus(BaseModel):
    overall_health: str  # "excellent", "good", "fair", "poor"
    health_score: int  # 0-100
    issues: List[str]  # List of identified issues
    recommendations: List[str]  # Recommendations for improvement
    flags: Dict[str, bool]  # Various status flags

# Club Monitoring Response Model
class ClubMonitoringResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    club_name: str
    captain_name: str
    captain_email: str
    activity_metrics: ClubActivityMetrics
    performance_summary: ClubPerformanceSummary
    health_status: ClubHealthStatus
    last_updated: str  # DD MMM YYYY HH:MM format
    monitoring_id: str

# ========================================
# Club Picks API Models
# ========================================

# Pick Status Enum
class PickStatus(str, Enum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    CANCELLED = "cancelled"
    VOID = "void"

# Pick Type Enum
class PickType(str, Enum):
    SINGLE = "single"
    PARLAY = "parlay"
    TEASER = "teaser"
    PROP = "prop"
    LIVE = "live"

# Submitted By Role Enum
class SubmittedByRole(str, Enum):
    CAPTAIN = "captain"
    MODERATOR = "moderator"
    ANALYST = "analyst"
    EDITOR = "editor"

# Club Pick Item Model
class ClubPickItem(BaseModel):
    pick_id: str
    title: str
    description: Optional[str] = None
    pick_type: PickType
    sport: Optional[str] = None
    odds: Optional[float] = None
    stake: Optional[float] = None
    potential_payout: Optional[float] = None
    submitted_by: str  # User name
    submitted_by_role: SubmittedByRole
    submitted_by_email: Optional[str] = None
    date_submitted: str  # DD MMM YYYY HH:MM format
    game_date: Optional[str] = None  # DD MMM YYYY HH:MM format
    status: PickStatus
    outcome_date: Optional[str] = None  # DD MMM YYYY HH:MM format
    profit_loss: Optional[float] = None
    tags: List[str] = []
    confidence_level: Optional[int] = Field(None, ge=1, le=10)  # 1-10 scale

# Club Picks Request Model
class ClubPicksRequest(BaseModel):
    status: Optional[PickStatus] = Field(None, description="Filter by pick status")
    pick_type: Optional[PickType] = Field(None, description="Filter by pick type")
    submitted_by_role: Optional[SubmittedByRole] = Field(None, description="Filter by submitter role")
    sport: Optional[str] = Field(None, description="Filter by sport")
    date_from: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    date_to: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    search: Optional[str] = Field(None, min_length=2, description="Search pick titles and descriptions")
    page: int = Field(1, ge=1, description="Page number")
    limit: int = Field(20, ge=1, le=100, description="Records per page")
    sort_by: str = Field("date_submitted", description="Sort field")
    sort_order: SortOrder = Field(SortOrder.DESC, description="Sort order")

# Club Picks Pagination Model
class ClubPicksPagination(BaseModel):
    current_page: int
    total_pages: int
    total_records: int
    records_per_page: int
    has_next: bool
    has_previous: bool

# Club Picks Summary Model
class ClubPicksSummary(BaseModel):
    total_picks: int
    pending_picks: int
    won_picks: int
    lost_picks: int
    cancelled_picks: int
    void_picks: int
    win_rate: float
    total_profit_loss: float
    avg_odds: Optional[float] = None
    most_active_contributor: Optional[str] = None

# Club Picks Response Model
class ClubPicksResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    club_name: str
    data: List[ClubPickItem]
    pagination: ClubPicksPagination
    summary: ClubPicksSummary
    filters_applied: Dict[str, Any]
    response_time_ms: Optional[float] = None

# ========================================
# Moderator Details API Models
# ========================================

# Moderator Profile Model
class ModeratorProfile(BaseModel):
    moderator_id: str
    full_name: str
    email: str
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: str  # DD MMM YYYY format
    status: ModeratorStatus
    last_login: Optional[str] = None  # DD MMM YYYY HH:mm format

# Assigned Club Captain Model
class AssignedByCaptain(BaseModel):
    captain_id: str
    captain_name: str
    captain_email: Optional[str] = None

# Assigned Club Details Model
class AssignedClubDetails(BaseModel):
    club_id: str
    club_name: str
    role: ModeratorRole
    assigned_by: AssignedByCaptain
    assigned_date: str  # DD MMM YYYY HH:mm format
    status: str  # active, inactive
    subscription_status: str  # active, cancelled, etc.

# Pick Submitted Model
class PickSubmitted(BaseModel):
    pick_id: str
    game_name: str
    title: str
    description: Optional[str] = None
    pick_type: str  # single, parlay, etc.
    sport: Optional[str] = None
    odds: Optional[float] = None
    stake: Optional[float] = None
    submission_date: str  # DD MMM YYYY HH:mm format
    game_date: Optional[str] = None  # DD MMM YYYY HH:mm format
    outcome: str  # Win, Loss, Pending, Cancelled, Void
    outcome_date: Optional[str] = None  # DD MMM YYYY HH:mm format
    profit_loss: Optional[float] = None
    tagged_pick: bool = False
    confidence_level: Optional[int] = None
    club_name: str

# Locker Room Action Type Enum
class LockerRoomActionType(str, Enum):
    MUTE_USER = "Mute User"
    UNMUTE_USER = "Unmute User"
    DELETE_POST = "Delete Post"
    DELETE_MESSAGE = "Delete Message"
    BAN_USER = "Ban User"
    UNBAN_USER = "Unban User"
    KICK_USER = "Kick User"
    WARN_USER = "Warn User"
    EDIT_MESSAGE = "Edit Message"
    PIN_MESSAGE = "Pin Message"
    UNPIN_MESSAGE = "Unpin Message"
    SLOW_MODE = "Enable Slow Mode"
    DISABLE_SLOW_MODE = "Disable Slow Mode"

# Locker Room Action Model
class LockerRoomAction(BaseModel):
    action_id: str
    action_type: LockerRoomActionType
    club_name: str
    club_id: str
    target_user: Optional[str] = None  # User who was acted upon
    action_date: str  # DD MMM YYYY HH:mm format
    reason: Optional[str] = None
    duration: Optional[str] = None  # For temporary actions like mute duration
    details: Optional[str] = None

# Win/Loss Statistics Model
class WinLossStats(BaseModel):
    total_picks: int
    win_count: int
    loss_count: int
    pending_count: int
    cancelled_count: int
    void_count: int
    win_rate: float  # Rounded to 2 decimal places
    loss_rate: float  # Rounded to 2 decimal places
    profit_loss: float
    avg_odds: Optional[float] = None
    best_streak: int
    current_streak: int
    total_stakes: float
    roi: float  # Return on investment percentage

# Moderator Details Data Model
class ModeratorDetailsData(BaseModel):
    profile: ModeratorProfile
    assigned_clubs: List[AssignedClubDetails]
    picks_submitted: List[PickSubmitted]
    locker_room_actions: List[LockerRoomAction]
    win_loss_stats: WinLossStats

# Moderator Details Response Model
class ModeratorDetailsResponse(BaseModel):
    success: bool
    message: str
    data: Optional[ModeratorDetailsData] = None
    error_code: Optional[str] = None
    response_time_ms: Optional[float] = None
    last_updated: str  # DD MMM YYYY HH:mm format

# Enhanced Club Search Request (for advanced search functionality)
class ClubAdvancedSearchRequest(BaseModel):
    # Filter parameters
    club_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full club name")
    owner_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full owner name")
    email: Optional[str] = Field(None, min_length=1, max_length=100, description="Partial or full email")
    phone: Optional[str] = Field(None, min_length=10, max_length=15, description="Exact phone number match")
    status: Optional[ClubStatus] = Field(None, description="Filter by status: approved, pending, suspended")
    
    # Date range filters
    date_from: Optional[datetime] = Field(None, description="Filter clubs created on/after this date")
    date_to: Optional[datetime] = Field(None, description="Filter clubs created on/before this date")
    
    # Sorting parameters
    sort_by: Optional[ClubSearchSortField] = Field(ClubSearchSortField.DATE_CREATED, description="Sort by field: club_name, owner_name, date_created, subscription_price, moderator_count, status")
    sort_order: Optional[SortOrder] = Field(SortOrder.DESC, description="Sort order: asc or desc")
    
    # Pagination parameters
    page: int = Field(1, ge=1, description="Page number (default: 1)")
    limit: int = Field(10, ge=1, le=100, description="Number of results per page (default: 10)")

    @validator('club_name')
    def validate_club_name(cls, v):
        if v:
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z0-9\s\-_&]+$', v):
                raise ValueError('Club name must contain only letters, numbers, spaces, hyphens, underscores, and ampersands')
        return v

    @validator('owner_name')
    def validate_owner_name(cls, v):
        if v:
            v = ' '.join(v.split())
            if not re.match(r'^[A-Za-z\s]+$', v):
                raise ValueError('Owner name must contain only letters and spaces')
        return v

    @validator('email')
    def validate_email(cls, v):
        if v:
            # Basic email format validation for partial matching
            v = v.strip().lower()
            if not re.match(r'^[a-zA-Z0-9._%+-]*@?[a-zA-Z0-9.-]*\.?[a-zA-Z]*$', v):
                raise ValueError('Invalid email format for search')
        return v

    @validator('phone')
    def validate_phone(cls, v):
        if v:
            # Remove spaces and special characters for exact matching
            v = re.sub(r'[^\d]', '', v)
            if len(v) < 10 or len(v) > 15:
                raise ValueError('Phone number must be between 10-15 digits')
        return v

    @validator('date_to')
    def validate_date_range(cls, v, values):
        if v and 'date_from' in values and values['date_from']:
            if v < values['date_from']:
                raise ValueError('date_to must be after date_from')
        return v

# Enhanced Club Search Response
class ClubAdvancedSearchResponse(BaseModel):
    success: bool
    message: str
    clubs: List[ClubResponse]
    pagination: ClubPaginationMetadata
    search_metadata: Dict[str, Any]
    total_results: int
    search_time_ms: int

# ========================================
# Captain Request Management Models (Request Submission & Approval)
# ========================================

# Moderator Request Status Enum
class ModeratorRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

# Moderator Action Type Enum
class ModeratorActionType(str, Enum):
    ADD = "add"
    EDIT = "edit"
    DELETE = "delete"

# Moderator Roles Enum
class ModeratorRoleType(str, Enum):
    CHAT_MODERATOR = "chat_moderator"
    PICK_POSTER = "pick_poster"
    CONTENT_REVIEWER = "content_reviewer"
    ANALYST = "analyst"
    EDITOR = "editor"

# Captain Request Submission Models
class CaptainModeratorRequestSubmission(BaseModel):
    action_type: ModeratorActionType = Field(..., description="Type of action requested")
    moderator_id: Optional[str] = Field(None, description="Moderator ID for edit/delete actions")
    moderator_data: Optional[Dict[str, Any]] = Field(None, description="Moderator data for add/edit actions")
    request_reason: str = Field(..., min_length=10, description="Detailed reason for the request")
    club_id: str = Field(..., description="Club ID associated with the request")

    @validator('moderator_id')
    def validate_moderator_id(cls, v, values):
        action_type = values.get('action_type')
        if action_type in [ModeratorActionType.EDIT, ModeratorActionType.DELETE] and not v:
            raise ValueError('moderator_id is required for edit and delete actions')
        if v:
            try:
                from bson import ObjectId
                ObjectId(v)
            except:
                raise ValueError('Invalid moderator ID format')
        return v

    @validator('moderator_data')
    def validate_moderator_data(cls, v, values):
        action_type = values.get('action_type')
        if action_type in [ModeratorActionType.ADD, ModeratorActionType.EDIT] and not v:
            raise ValueError('moderator_data is required for add and edit actions')
        
        if v and action_type == ModeratorActionType.ADD:
            required_fields = ['moderator_name', 'email', 'assigned_clubs', 'roles']
            for field in required_fields:
                if field not in v:
                    raise ValueError(f'{field} is required in moderator_data for add action')
        
        return v

    @validator('club_id')
    def validate_club_id(cls, v):
        try:
            from bson import ObjectId
            ObjectId(v)
        except:
            raise ValueError('Invalid club ID format')
        return v

# Captain Request Response Models
class CaptainRequestData(BaseModel):
    request_id: str
    action_type: str
    moderator_id: Optional[str]
    moderator_data: Optional[Dict[str, Any]]
    request_reason: str
    request_status: str
    requested_by_captain_id: str
    captain_name: str
    club_id: str
    club_name: Optional[str]
    request_timestamp: str
    approved_by_admin_id: Optional[str]
    approved_by_admin_name: Optional[str]
    approval_timestamp: Optional[str]
    rejection_reason: Optional[str]

class CaptainRequestSubmissionResponse(BaseModel):
    success: bool
    message: str
    request: Optional[CaptainRequestData] = None
    request_id: str

# Admin Request Approval Models
class AdminRequestApprovalRequest(BaseModel):
    action: str = Field(..., description="Action to take: 'approve' or 'reject'")
    admin_notes: Optional[str] = Field(None, description="Admin notes for the decision")
    rejection_reason: Optional[str] = Field(None, description="Reason for rejection (required if rejecting)")

    @validator('action')
    def validate_action(cls, v):
        if v not in ['approve', 'reject']:
            raise ValueError('Action must be either "approve" or "reject"')
        return v

    @validator('rejection_reason')
    def validate_rejection_reason(cls, v, values):
        action = values.get('action')
        if action == 'reject' and not v:
            raise ValueError('rejection_reason is required when rejecting a request')
        if v and len(v.strip()) < 10:
            raise ValueError('rejection_reason must be at least 10 characters')
        return v

class AdminRequestApprovalResponse(BaseModel):
    success: bool
    message: str
    request: Optional[CaptainRequestData] = None
    action_taken: str

# Captain Request List Models
class CaptainRequestListRequest(BaseModel):
    status: Optional[ModeratorRequestStatus] = Field(None, description="Filter by request status")
    action_type: Optional[ModeratorActionType] = Field(None, description="Filter by action type")
    captain_id: Optional[str] = Field(None, description="Filter by captain ID")
    club_id: Optional[str] = Field(None, description="Filter by club ID")
    date_from: Optional[str] = Field(None, description="Filter from date (YYYY-MM-DD)")
    date_to: Optional[str] = Field(None, description="Filter to date (YYYY-MM-DD)")
    page: int = Field(1, ge=1, description="Page number for pagination")
    limit: int = Field(20, ge=1, le=100, description="Number of records per page")

    @validator('captain_id', 'club_id')
    def validate_object_ids(cls, v):
        if v:
            try:
                from bson import ObjectId
                ObjectId(v)
            except:
                raise ValueError('Invalid ID format')
        return v

    @validator('date_from', 'date_to')
    def validate_dates(cls, v):
        if v:
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise ValueError('Date must be in YYYY-MM-DD format')
        return v

class CaptainRequestListPagination(BaseModel):
    current_page: int
    total_pages: int
    total_records: int
    records_per_page: int
    has_next: bool
    has_previous: bool

class CaptainRequestListResponse(BaseModel):
    success: bool
    message: str
    requests: List[CaptainRequestData]
    pagination: CaptainRequestListPagination
    filters_applied: Dict[str, Any]
    total_pending: int
    total_approved: int
    total_rejected: int

# ========================================
# Moderator Management Models (CRUD with Captain Approval)
# ========================================

# Captain Request Model for Moderator Actions
class ModeratorRequest(BaseModel):
    request_id: str = Field(..., description="Unique request identifier")
    action_type: ModeratorActionType = Field(..., description="Type of action requested")
    moderator_id: Optional[str] = Field(None, description="Moderator ID for edit/delete actions")
    moderator_data: Optional[Dict[str, Any]] = Field(None, description="Moderator data for add/edit actions")
    request_reason: str = Field(..., description="Reason for the request")
    request_status: ModeratorRequestStatus = Field(..., description="Current status of request")
    requested_by_captain_id: str = Field(..., description="Captain who made the request")
    captain_name: Optional[str] = Field(None, description="Captain's name")
    club_id: str = Field(..., description="Club associated with the request")
    request_timestamp: datetime = Field(..., description="When the request was made")
    approved_by_admin_id: Optional[str] = Field(None, description="Admin who approved the request")
    approval_timestamp: Optional[datetime] = Field(None, description="When the request was approved")

    @validator('request_id')
    def validate_request_id(cls, v):
        if not v or len(v.strip()) < 5:
            raise ValueError('Request ID must be at least 5 characters')
        return v.strip()

    @validator('request_reason')
    def validate_request_reason(cls, v):
        if not v or len(v.strip()) < 10:
            raise ValueError('Request reason must be at least 10 characters')
        return v.strip()

# Moderator Create Request Model
class ModeratorCreateRequest(BaseModel):
    request_id: str = Field(..., description="Approved Captain request ID")
    moderator_name: str = Field(..., min_length=2, max_length=100, description="Full name of moderator")
    email: EmailStr = Field(..., description="Email address (must be unique)")
    phone: Optional[str] = Field(None, description="Phone number")
    assigned_clubs: List[str] = Field(..., min_items=1, description="List of club IDs to assign")
    roles: List[ModeratorRoleType] = Field(..., min_items=1, description="List of moderator roles")

    @validator('phone')
    def validate_phone(cls, v):
        if v:
            v = v.strip()
            # Basic phone validation - allow +, digits, spaces, hyphens
            import re
            if not re.match(r'^[\+]?[1-9][\d\s\-]{7,14}$', v.replace(' ', '').replace('-', '')):
                raise ValueError('Invalid phone number format')
        return v

    @validator('assigned_clubs')
    def validate_assigned_clubs(cls, v):
        if not v:
            raise ValueError('At least one club must be assigned')
        # Validate ObjectId format for each club
        for club_id in v:
            try:
                from bson import ObjectId
                ObjectId(club_id)
            except:
                raise ValueError(f'Invalid club ID format: {club_id}')
        return v

# Moderator Update Request Model
class ModeratorUpdateRequest(BaseModel):
    request_id: str = Field(..., description="Approved Captain request ID")
    moderator_name: Optional[str] = Field(None, min_length=2, max_length=100, description="Full name of moderator")
    email: Optional[EmailStr] = Field(None, description="Email address (must be unique)")
    phone: Optional[str] = Field(None, description="Phone number")
    assigned_clubs: Optional[List[str]] = Field(None, description="List of club IDs to assign")
    roles: Optional[List[ModeratorRoleType]] = Field(None, description="List of moderator roles")

    @validator('phone')
    def validate_phone(cls, v):
        if v:
            v = v.strip()
            import re
            if not re.match(r'^[\+]?[1-9][\d\s\-]{7,14}$', v.replace(' ', '').replace('-', '')):
                raise ValueError('Invalid phone number format')
        return v

    @validator('assigned_clubs')
    def validate_assigned_clubs(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError('If provided, at least one club must be assigned')
        if v:
            for club_id in v:
                try:
                    from bson import ObjectId
                    ObjectId(club_id)
                except:
                    raise ValueError(f'Invalid club ID format: {club_id}')
        return v

    @validator('roles')
    def validate_roles(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError('If provided, at least one role must be assigned')
        return v

# Moderator Delete Request Model
class ModeratorDeleteRequest(BaseModel):
    request_id: str = Field(..., description="Approved Captain request ID")
    delete_reason: Optional[str] = Field(None, description="Additional reason for deletion")

# Moderator Response Models
class ModeratorData(BaseModel):
    moderator_id: str
    moderator_name: str
    email: str
    phone: Optional[str]
    assigned_clubs: List[Dict[str, str]]  # [{club_id, club_name}]
    roles: List[str]
    is_active: bool
    created_by_admin_id: str
    created_by_admin_name: Optional[str]
    created_timestamp: str
    last_updated_timestamp: Optional[str]

class ModeratorCreateResponse(BaseModel):
    success: bool
    message: str
    moderator: Optional[ModeratorData] = None
    request_id: str
    action_logged: bool

class ModeratorUpdateResponse(BaseModel):
    success: bool
    message: str
    moderator: Optional[ModeratorData] = None
    request_id: str
    action_logged: bool
    changes_made: List[str]

class ModeratorDeleteResponse(BaseModel):
    success: bool
    message: str
    request_id: str
    action_logged: bool
    deleted_moderator_id: str

# Audit Log Entry Model
class ModeratorAuditLogEntry(BaseModel):
    log_id: str
    action_type: ModeratorActionType
    moderator_id: Optional[str]
    admin_id: str
    admin_name: str
    captain_id: str
    captain_name: str
    club_id: str
    request_id: str
    request_reason: str
    action_timestamp: datetime
    action_result: str  # "success" or "denied"
    error_message: Optional[str] = None

    changes_made: Optional[List[str]] = None

# ========================================
# SUBSCRIPTION PLANS MODELS
# ========================================

# Subscription Plan Type Enum
class SubscriptionPlanType(str, Enum):
    TRIAL = "Trial"
    MONTHLY_CLUB_MEMBERSHIP = "Monthly Club Membership"
    CLUB_OWNERSHIP = "Club Ownership"
    PREMIUM_MEMBERSHIP = "Premium Membership"
    BASIC_MEMBERSHIP = "Basic Membership"
    VIP_MEMBERSHIP = "VIP Membership"

# Subscription Status Enum
class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PENDING = "pending"
    SUSPENDED = "suspended"

# Plan Status Enum
class PlanStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"
    ARCHIVED = "archived"

# Subscription Plan Sort Field Enum
class SubscriptionPlanSortField(str, Enum):
    NAME = "name"
    TYPE = "type"
    PRICE = "price"
    ACTIVE_SUBSCRIBERS = "active_subscribers"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"

# Subscription Plan Base Model
class SubscriptionPlan(BaseModel):
    plan_id: str = Field(..., description="Unique plan identifier")
    name: str = Field(..., min_length=1, max_length=100, description="Plan name")
    thumbnail_url: Optional[str] = Field(None, description="Thumbnail image link")
    type: SubscriptionPlanType = Field(..., description="Plan type")
    price: float = Field(..., ge=0, description="Plan price")
    is_active: bool = Field(True, description="Indicates if plan is available")
    created_at: str = Field(..., description="Creation date")
    updated_at: str = Field(..., description="Last updated date")
    active_subscribers: int = Field(0, ge=0, description="Number of active subscribers")
    description: Optional[str] = Field(None, description="Plan description")
    features: Optional[List[str]] = Field(None, description="List of plan features")
    duration_days: Optional[int] = Field(None, ge=1, description="Plan duration in days")

# Subscription Plan List Request Model
class SubscriptionPlanListRequest(BaseModel):
    search: Optional[str] = Field(None, min_length=1, max_length=100, description="Search by name or type")
    type: Optional[SubscriptionPlanType] = Field(None, description="Filter by plan type")
    is_active: Optional[bool] = Field(None, description="Filter by active status")
    price_min: Optional[float] = Field(None, ge=0, description="Minimum price filter")
    price_max: Optional[float] = Field(None, ge=0, description="Maximum price filter")
    sort_by: SubscriptionPlanSortField = Field(SubscriptionPlanSortField.NAME, description="Field to sort by")
    sort_order: SortOrder = Field(SortOrder.ASC, description="Sort order")
    page: int = Field(1, ge=1, description="Page number")
    limit: int = Field(20, ge=1, le=100, description="Items per page")

    @validator('price_max')
    def validate_price_range(cls, v, values):
        if v and 'price_min' in values and values['price_min']:
            if v < values['price_min']:
                raise ValueError('price_max must be greater than or equal to price_min')
        return v

# Subscription Plan List Pagination Model
class SubscriptionPlanListPagination(BaseModel):
    current_page: int = Field(..., description="Current page number")
    total_pages: int = Field(..., description="Total number of pages")
    total_records: int = Field(..., description="Total number of records")
    records_per_page: int = Field(..., description="Number of records per page")
    has_next: bool = Field(..., description="Whether there is a next page")
    has_previous: bool = Field(..., description="Whether there is a previous page")

# Subscription Plan List Response Model
class SubscriptionPlanListResponse(BaseModel):
    success: bool = Field(..., description="Whether the request was successful")
    message: str = Field(..., description="Response message")
    plans: List[SubscriptionPlan] = Field(..., description="List of subscription plans")
    pagination: SubscriptionPlanListPagination = Field(..., description="Pagination information")
    filters_applied: Dict[str, Any] = Field(..., description="Filters that were applied")
    summary: Dict[str, Any] = Field(..., description="Summary statistics")

# Subscription Plan CSV Export Request Model
class SubscriptionPlanCSVExportRequest(BaseModel):
    search: Optional[str] = Field(None, min_length=1, max_length=100, description="Search by name or type")
    type: Optional[SubscriptionPlanType] = Field(None, description="Filter by plan type")
    is_active: Optional[bool] = Field(None, description="Filter by active status")
    price_min: Optional[float] = Field(None, ge=0, description="Minimum price filter")
    price_max: Optional[float] = Field(None, ge=0, description="Maximum price filter")
    fields: List[str] = Field(["name", "type", "price", "active_subscribers"], description="Fields to include in CSV")
    sort_by: SubscriptionPlanSortField = Field(SubscriptionPlanSortField.NAME, description="Field to sort by")
    sort_order: SortOrder = Field(SortOrder.ASC, description="Sort order")

    @validator('fields')
    def validate_fields(cls, v):
        valid_fields = ["name", "type", "price", "active_subscribers", "is_active", "created_at", "updated_at", "description"]
        for field in v:
            if field not in valid_fields:
                raise ValueError(f'Invalid field: {field}. Valid fields are: {valid_fields}')
        return v

# Subscription Plan CSV Export Response Model
class SubscriptionPlanCSVExportResponse(BaseModel):
    success: bool = Field(..., description="Whether the export was successful")
    message: str = Field(..., description="Response message")
    csv_data: str = Field(..., description="CSV data as string")
    filename: str = Field(..., description="Suggested filename for download")
    total_records: int = Field(..., description="Total number of records exported")
    fields_exported: List[str] = Field(..., description="Fields included in export")

# Subscription Plan Details Model
class SubscriptionPlanDetails(BaseModel):
    plan_id: str = Field(..., description="Unique plan identifier")
    name: str = Field(..., description="Plan name")
    thumbnail_url: Optional[str] = Field(None, description="Thumbnail image link")
    type: SubscriptionPlanType = Field(..., description="Plan type")
    price: float = Field(..., description="Plan price")
    is_active: bool = Field(..., description="Indicates if plan is available")
    created_at: str = Field(..., description="Creation date")
    updated_at: str = Field(..., description="Last updated date")
    active_subscribers: int = Field(..., description="Number of active subscribers")
    description: Optional[str] = Field(None, description="Plan description")
    features: Optional[List[str]] = Field(None, description="List of plan features")
    duration_days: Optional[int] = Field(None, description="Plan duration in days")
    total_revenue: Optional[float] = Field(None, description="Total revenue from this plan")
    average_subscription_duration: Optional[float] = Field(None, description="Average subscription duration in days")

# Subscription Plan Analytics Model
class SubscriptionPlanAnalytics(BaseModel):
    plan_id: str = Field(..., description="Unique plan identifier")
    plan_name: str = Field(..., description="Plan name")
    total_subscriptions: int = Field(..., description="Total number of subscriptions")
    active_subscriptions: int = Field(..., description="Number of active subscriptions")
    cancelled_subscriptions: int = Field(..., description="Number of cancelled subscriptions")
    expired_subscriptions: int = Field(..., description="Number of expired subscriptions")
    total_revenue: float = Field(..., description="Total revenue generated")
    monthly_recurring_revenue: float = Field(..., description="Monthly recurring revenue")
    churn_rate: float = Field(..., description="Churn rate percentage")
    average_subscription_duration: float = Field(..., description="Average subscription duration in days")

# Subscription Plan Status Update Request Model
class SubscriptionPlanStatusUpdateRequest(BaseModel):
    plan_id: str = Field(..., description="Plan ID to update")
    is_active: bool = Field(..., description="New active status")

# Subscription Plan Status Update Response Model
class SubscriptionPlanStatusUpdateResponse(BaseModel):
    success: bool = Field(..., description="Whether the update was successful")
    message: str = Field(..., description="Response message")
    plan_id: str = Field(..., description="Updated plan ID")
    previous_status: bool = Field(..., description="Previous active status")
    new_status: bool = Field(..., description="New active status")
    updated_at: str = Field(..., description="Update timestamp")

# Subscription Plan Delete Response Model
class SubscriptionPlanDeleteResponse(BaseModel):
    success: bool = Field(..., description="Whether the deletion was successful")
    message: str = Field(..., description="Response message")
    plan_id: str = Field(..., description="Deleted plan ID")
    deleted_at: str = Field(..., description="Deletion timestamp")

# ============================================================================
# INCLUSIONS AND SPORTS MODELS
# ============================================================================

class InclusionCreateRequest(BaseModel):
    """Request model for creating inclusions"""
    title: str = Field(..., min_length=3, max_length=100, description="Inclusion title")
    sub_desc: str = Field(..., min_length=5, max_length=200, description="Inclusion description")
    logo_url: Optional[str] = Field(None, description="URL to inclusion logo/icon")

class InclusionResponse(BaseModel):
    """Response model for inclusions"""
    id: str = Field(..., description="Inclusion ID")
    title: str = Field(..., description="Inclusion title")
    sub_desc: str = Field(..., description="Inclusion description")
    logo_url: Optional[str] = Field(None, description="URL to inclusion logo/icon")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        arbitrary_types_allowed = True
        populate_by_name = True

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper datetime serialization"""
        data = super().model_dump(*args, **kwargs)
        # Ensure datetime objects are ISO formatted strings
        if isinstance(data.get('created_at'), datetime):
            data['created_at'] = data['created_at'].isoformat()
        if isinstance(data.get('updated_at'), datetime):
            data['updated_at'] = data['updated_at'].isoformat()
        return data

class InclusionUpdateRequest(BaseModel):
    """Request model for updating inclusions"""
    title: Optional[str] = Field(None, min_length=3, max_length=100, description="Inclusion title")
    sub_desc: Optional[str] = Field(None, min_length=5, max_length=200, description="Inclusion description")
    logo_url: Optional[str] = Field(None, description="URL to inclusion logo/icon")

class InclusionListResponse(BaseModel):
    """Response model for listing inclusions"""
    inclusions: List[InclusionResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper datetime serialization for nested items"""
        data = super().model_dump(*args, **kwargs)
        # Ensure nested InclusionResponse objects are properly serialized
        if data.get('inclusions'):
            serialized_inclusions = []
            for inclusion in data['inclusions']:
                try:
                    if hasattr(inclusion, 'model_dump') and callable(getattr(inclusion, 'model_dump')):
                        # If it's a Pydantic model, call its model_dump method
                        serialized_inclusions.append(inclusion.model_dump())
                    else:
                        # If it's already a dict or other type, handle it safely
                        if isinstance(inclusion, dict):
                            inclusion_dict = dict(inclusion)
                        else:
                            # Convert to dict if possible
                            inclusion_dict = inclusion.__dict__ if hasattr(inclusion, '__dict__') else dict(inclusion)
                        
                        # Ensure datetime fields are serialized
                        if isinstance(inclusion_dict.get('created_at'), datetime):
                            inclusion_dict['created_at'] = inclusion_dict['created_at'].isoformat()
                        if isinstance(inclusion_dict.get('updated_at'), datetime):
                            inclusion_dict['updated_at'] = inclusion_dict['updated_at'].isoformat()
                        serialized_inclusions.append(inclusion_dict)
                except Exception as e:
                    print(f"DEBUG: Error serializing inclusion: {e}, inclusion: {inclusion}")
                    # Fallback: try to convert to string representation
                    serialized_inclusions.append(str(inclusion))
            data['inclusions'] = serialized_inclusions
        return data

class SportCreateRequest(BaseModel):
    """Request model for creating sports"""
    name: str = Field(..., min_length=2, max_length=50, description="Sport name")
    icon: str = Field(..., description="URL to sport icon")

class SportResponse(BaseModel):
    """Response model for sports"""
    id: str = Field(..., description="Sport ID")
    name: str = Field(..., description="Sport name")
    icon: str = Field(..., description="URL to sport icon")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        arbitrary_types_allowed = True
        populate_by_name = True

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper datetime serialization"""
        data = super().model_dump(*args, **kwargs)
        # Ensure datetime objects are ISO formatted strings
        if isinstance(data.get('created_at'), datetime):
            data['created_at'] = data['created_at'].isoformat()
        if isinstance(data.get('updated_at'), datetime):
            data['updated_at'] = data['updated_at'].isoformat()
        return data

class SportUpdateRequest(BaseModel):
    """Request model for updating sports"""
    name: Optional[str] = Field(None, min_length=2, max_length=50, description="Sport name")
    icon: Optional[str] = Field(None, description="URL to sport icon")

class SportListResponse(BaseModel):
    """Response model for listing sports"""
    sports: List[SportResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool

    def dict(self, *args, **kwargs):
        """Convert to dict with proper datetime serialization for nested items"""
        data = super().dict(*args, **kwargs)
        # Ensure nested SportResponse objects are properly serialized
        if data.get('sports'):
            serialized_sports = []
            for sport in data['sports']:
                try:
                    if hasattr(sport, 'dict') and callable(getattr(sport, 'dict')):
                        # If it's a Pydantic model, call its dict method
                        serialized_sports.append(sport.dict())
                    else:
                        # If it's already a dict or other type, handle it safely
                        if isinstance(sport, dict):
                            sport_dict = dict(sport)
                        else:
                            # Convert to dict if possible
                            sport_dict = sport.__dict__ if hasattr(sport, '__dict__') else dict(sport)
                        
                        # Ensure datetime fields are serialized
                        if isinstance(sport_dict.get('created_at'), datetime):
                            sport_dict['created_at'] = sport_dict['created_at'].isoformat()
                        if isinstance(sport_dict.get('updated_at'), datetime):
                            sport_dict['updated_at'] = sport_dict['updated_at'].isoformat()
                        serialized_sports.append(sport_dict)
                except Exception as e:
                    print(f"DEBUG: Error serializing sport: {e}, sport: {sport}")
                    # Fallback: try to convert to string representation
                    serialized_sports.append(str(sport))
            data['sports'] = serialized_sports
        return data

# Database models for inclusions and sports
class InclusionDocument(BaseModel):
    """Database document model for inclusions"""
    title: str
    sub_desc: str
    logo_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    def dict(self, *args, **kwargs):
        """Convert to dict with proper datetime serialization"""
        data = super().dict(*args, **kwargs)
        # For MongoDB insertion, we want to keep datetime objects as they are
        # MongoDB can handle datetime objects natively
        return data

class SportDocument(BaseModel):
    """Database document model for sports"""
    name: str
    icon: str
    created_at: datetime
    updated_at: datetime

    def dict(self, *args, **kwargs):
        """Convert to dict with proper datetime serialization"""
        data = super().dict(*args, **kwargs)
        # For MongoDB insertion, we want to keep datetime objects as they are
        # MongoDB can handle datetime objects natively
        return data

# Admin Deletion Models
class AdminDeletionUserRole(str, Enum):
    """User roles that can be deleted by admin"""
    MEMBER = "Member"
    CAPTAIN = "Captain"
    MODERATOR = "Moderator"

class AdminDeletionType(str, Enum):
    """Types of admin deletion"""
    PERMANENT = "permanent"
    TEMPORARY = "temporary"

class AdminDeletionRequest(BaseModel):
    """Request model for admin deletion of users"""
    user_id: str = Field(..., description="ID of the user to delete")
    user_role: AdminDeletionUserRole = Field(..., description="Role of the user (member/captain/moderator)")
    deletion_type: AdminDeletionType = Field(..., description="Type of deletion (permanent/temporary)")
    reason: str = Field(..., min_length=10, max_length=500, description="Reason for deletion")
    admin_notes: Optional[str] = Field(None, max_length=1000, description="Internal admin notes")
    notify_user: bool = Field(True, description="Whether to send email notification to user")

class AdminDeletionResponse(BaseModel):
    """Response model for admin deletion"""
    success: bool = Field(..., description="Whether the deletion was successful")
    message: str = Field(..., description="Response message")
    user_id: str = Field(..., description="ID of the deleted user")
    user_role: AdminDeletionUserRole = Field(..., description="Role of the deleted user")
    deletion_type: AdminDeletionType = Field(..., description="Type of deletion performed")
    previous_status: str = Field(..., description="Previous status of the user")
    new_status: str = Field(..., description="New status of the user")
    affected_clubs: List[str] = Field(default_factory=list, description="List of affected club IDs")
    affected_members: List[str] = Field(default_factory=list, description="List of affected member IDs")
    stripe_actions: List[Dict] = Field(default_factory=list, description="Stripe actions performed")
    notification_sent: bool = Field(False, description="Whether notification was sent")
    admin_email: str = Field(..., description="Admin who performed the deletion")
    timestamp: datetime = Field(..., description="Timestamp of the deletion")
    deletion_id: str = Field(..., description="Unique deletion ID for tracking")

class AdminReactivationRequest(BaseModel):
    """Request model for admin reactivation of users"""
    user_id: str = Field(..., description="ID of the user to reactivate")
    user_role: AdminDeletionUserRole = Field(..., description="Role of the user (member/captain/moderator)")
    reason: str = Field(..., min_length=10, max_length=500, description="Reason for reactivation")
    admin_notes: Optional[str] = Field(None, max_length=1000, description="Internal admin notes")
    notify_user: bool = Field(True, description="Whether to send email notification to user")

class AdminReactivationResponse(BaseModel):
    """Response model for admin reactivation"""
    success: bool = Field(..., description="Whether the reactivation was successful")
    message: str = Field(..., description="Response message")
    user_id: str = Field(..., description="ID of the reactivated user")
    user_role: AdminDeletionUserRole = Field(..., description="Role of the reactivated user")
    previous_status: str = Field(..., description="Previous status of the user")
    new_status: str = Field(..., description="New status of the user")
    affected_clubs: List[str] = Field(default_factory=list, description="List of affected club IDs")
    affected_members: List[str] = Field(default_factory=list, description="List of affected member IDs")
    stripe_actions: List[Dict] = Field(default_factory=list, description="Stripe actions performed")
    notification_sent: bool = Field(False, description="Whether notification was sent")
    admin_email: str = Field(..., description="Admin who performed the reactivation")
    timestamp: datetime = Field(..., description="Timestamp of the reactivation")
    reactivation_id: str = Field(..., description="Unique reactivation ID for tracking")


