from pydantic import BaseModel, Field, field_validator, HttpUrl, ConfigDict
from typing import Optional, List, Literal, Union, Dict, Any
from datetime import datetime
from enum import Enum
from bson import ObjectId
from fastapi.encoders import jsonable_encoder
import uuid


class PricingPlan(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


class ClubCategory(str, Enum):
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    INVESTMENT = "investment"
    GENERAL = "general"


class SortOption(str, Enum):
    TOP_PERFORMING = "top_performing"  # by win_pct desc
    NEWEST = "newest"  # by created_at desc
    MOST_MEMBERS = "most_members"  # by member_count desc
    POPULAR = "popular"  # single club with max member_count


class WhatsIncludedItem(BaseModel):
    """Model for individual items in the whats_included list"""

    title: str = Field(description="Title of the benefit/feature")
    sub_desc: str = Field(description="Sub description of the benefit/feature")
    logo_url: str = Field(description="URL to the logo/icon for this benefit")


class ClubPricing(BaseModel):
    plan: PricingPlan
    price: float = Field(..., gt=0, description="Price must be greater than 0")
    currency: str = Field(default="USD", description="Currency code")


class ClubCreateRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=100, description="Club name")
    description: str = Field(
        ..., min_length=10, max_length=500, description="Club description"
    )
    sub_description: Optional[str] = Field(
        None,
        min_length=5,
        max_length=200,
        description="Short subtitle or tagline for the club",
    )
    logo_url: Optional[str] = Field(None, description="URL to club logo/image")
    category: ClubCategory = Field(..., description="Club category")
    pricing_plans: List[ClubPricing] = Field(
        default_factory=list,
        min_items=1,
        description="At least one pricing plan required",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Club name cannot be empty")
        return v.strip()

    @field_validator("pricing_plans")
    @classmethod
    def validate_pricing_plans(cls, v):
        if not v:
            raise ValueError("At least one pricing plan is required")

        # Check for duplicate plans
        plans = [plan.plan for plan in v]
        if len(plans) != len(set(plans)):
            raise ValueError("Duplicate pricing plans are not allowed")

        return v


class ClubUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, min_length=10, max_length=500)
    sub_description: Optional[str] = Field(
        None,
        min_length=5,
        max_length=200,
        description="Short subtitle or tagline for the club",
    )
    logo_url: Optional[str] = None
    category: Optional[ClubCategory] = None
    pricing_plans: Optional[List[ClubPricing]] = None
    is_active: Optional[bool] = None


class ClubFilters(BaseModel):
    search: Optional[str] = Field(
        None, description="Search by club name or captain name"
    )
    category: Optional[ClubCategory] = None
    min_win_pct: Optional[float] = Field(
        None, ge=0, le=100, description="Minimum win percentage"
    )
    max_win_pct: Optional[float] = Field(
        None, ge=0, le=100, description="Maximum win percentage"
    )
    min_price: Optional[float] = Field(None, ge=0, description="Minimum price")
    max_price: Optional[float] = Field(None, ge=0, description="Maximum price")
    pricing_plan: Optional[PricingPlan] = None


class ClubCaptain(BaseModel):
    id: str
    full_name: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    name_based_id: str = Field(description="URL-friendly ID based on captain name")


class ClubResponse(BaseModel):
    id: str
    name: str
    description: str
    sub_description: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    category: Optional[ClubCategory] = None
    win_pct: float = Field(default=0.0, description="Win percentage")
    member_count: int = Field(default=0, description="Number of members")
    total_bets: int = Field(default=0, description="Total number of bets")
    pricing_plans: List[ClubPricing] = Field(default_factory=list)
    captain: Optional[dict] = None
    whats_included: Optional[List[WhatsIncludedItem]] = None
    top_3_sports: Optional[List[dict]] = None
    is_active: bool = Field(default=True)
    is_popular: bool = Field(
        default=False, description="Whether this club is marked as popular"
    )
    name_based_id: str = Field(description="URL-friendly ID based on club name")
    created_at: datetime
    # User trial club statistics
    clubs_joined_count: int = Field(default=0, description="Number of clubs the user has joined")
    clubs_remaining: int = Field(default=0, description="Number of clubs remaining in trial period")
    max_clubs: int = Field(default=4, description="Maximum number of clubs allowed during trial period")
    updated_at: datetime

class ClubListResponse(BaseModel):
    clubs: List[ClubResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


class UserClubInfo(BaseModel):
    """Simplified club information for user's club list"""

    club_id: str = Field(..., description="Club ObjectId")
    name: str = Field(..., description="Club name")
    name_based_id: str = Field(..., description="Club name-based ID")
    description: Optional[str] = Field(None, description="Club description")
    logo_url: Optional[str] = Field(None, description="Club logo URL")
    member_count: int = Field(default=0, description="Number of members")
    moderator_count: int = Field(default=0, description="Number of moderators")
    is_active: bool = Field(default=True, description="Whether club is active")
    created_at: datetime = Field(..., description="Club creation date")
    user_role: str = Field(..., description="User's role in this club (captain/member)")


class UserClubsResponse(BaseModel):
    """Response model for user's clubs list"""

    clubs: List[UserClubInfo] = Field(
        ..., description="List of clubs user has access to"
    )
    total_count: int = Field(..., description="Total number of clubs")
    total_members: int = Field(default=0, description="Total members across all clubs")
    total_moderators: int = Field(default=0, description="Total moderators across all clubs")
    user_role: str = Field(..., description="User's role (Captain/Member)")
    message: str = Field(..., description="Response message")


class ClubStatsResponse(BaseModel):
    """Response model for captain's club statistics"""

    total_clubs: int = Field(
        ..., description="Total number of clubs created by captain"
    )
    total_members: int = Field(..., description="Total members across all clubs")
    total_revenue: float = Field(
        ..., description="Total revenue generated from all clubs"
    )
    average_win_percentage: float = Field(
        ..., description="Average win percentage across all clubs"
    )
    captain_id: str = Field(..., description="Captain's user ID")
    captain_name: str = Field(..., description="Captain's full name")
    message: str = Field(..., description="Response message")


class ClubCreateResponse(BaseModel):
    message: str
    club_id: str
    club: ClubResponse


class ClubUpdateResponse(BaseModel):
    message: str
    club: ClubResponse


class ClubDeleteResponse(BaseModel):
    message: str
    club_id: str


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class ClubSearchRequest(BaseModel):
    filters: Optional[ClubFilters] = None
    sort_by: SortOption = Field(default=SortOption.TOP_PERFORMING)
    pagination: PaginationParams = Field(default_factory=PaginationParams)


# Database models (internal use)
class ClubDocument(BaseModel):
    """Internal model representing club document in MongoDB"""

    name: str
    description: str
    sub_description: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    category: str
    pricing_plans: List[dict]
    captain_id: str
    win_pct: float = 0.0
    member_count: int = 0
    total_bets: int = 0
    winning_bets: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


# Additional models for detailed club views
class CaptainDetails(BaseModel):
    id: str
    full_name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    total_picks: int = Field(default=0, description="Total betting picks made")
    win_pct: float = Field(default=0.0, description="Captain's win percentage")
    member_count: int = Field(
        default=0, description="Total members across all captain's clubs"
    )
    clubs_count: int = Field(default=0, description="Number of clubs owned by captain")
    joined_date: Optional[datetime] = None


class ClubStats(BaseModel):
    total_picks: int = Field(default=0, description="Total picks for this club")
    winning_picks: int = Field(default=0, description="Number of winning picks")
    win_pct: float = Field(default=0.0, description="Club win percentage")
    member_count: int = Field(default=0, description="Current member count")
    total_revenue: Optional[float] = Field(
        default=0.0, description="Total revenue generated"
    )
    created_at: datetime
    last_pick_date: Optional[datetime] = None


class MembershipInfo(BaseModel):
    is_member: bool = Field(default=False)
    membership_plan: Optional[PricingPlan] = None
    joined_date: Optional[datetime] = None
    expires_date: Optional[datetime] = None
    subscription_status: Optional[str] = None  # active, expired, cancelled
    can_access_premium: bool = Field(default=False)


class ClubPreview(BaseModel):
    """Limited club info for non-members"""

    id: str
    name: str
    description: str
    sub_description: Optional[str] = None
    logo_url: Optional[str] = None
    category: ClubCategory
    win_pct: float
    member_count: int
    pricing_plans: List[ClubPricing] = Field(default_factory=list)
    captain: ClubCaptain
    is_preview: bool = Field(default=True)
    recent_picks_count: int = Field(
        default=0, description="Number of recent picks (without details)"
    )


class ClubFullDetails(BaseModel):
    """Complete club info for members"""

    id: str
    name: str
    description: str
    sub_description: Optional[str] = None
    logo_url: Optional[str] = None
    category: ClubCategory
    bio: Optional[str] = None  # Extended description for members
    pricing_plans: List[ClubPricing] = Field(default_factory=list)
    captain: CaptainDetails
    stats: ClubStats
    membership_info: MembershipInfo
    is_preview: bool = Field(default=False)
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    # Member-only content
    recent_picks: Optional[List[dict]] = None  # Betting picks for members
    member_benefits: Optional[List[str]] = None  # List of member benefits
    exclusive_content: Optional[dict] = None  # Any exclusive content


class ClubDetailsResponse(BaseModel):
    """Union response that can be either preview or full details"""

    club: Union[ClubPreview, ClubFullDetails]
    user_membership: Optional[MembershipInfo] = None
    can_join: bool = Field(default=True, description="Whether user can join this club")
    join_requirements: Optional[List[str]] = None


class CaptainInfoResponse(BaseModel):
    captain: CaptainDetails
    clubs: List[ClubResponse] = Field(
        default=[], description="Other clubs by this captain"
    )
    total_stats: dict = Field(
        default={}, description="Aggregated stats across all clubs"
    )


class MembershipStatusResponse(BaseModel):
    is_member: bool
    membership_info: Optional[MembershipInfo] = None
    club_id: str
    club_name: str
    available_plans: List[ClubPricing] = Field(
        default=[], description="Available subscription plans"
    )
    can_join: bool = Field(default=True)
    join_restrictions: Optional[List[str]] = None


# Trial Membership Models
class TrialLimits(BaseModel):
    max_clubs: int = Field(default=4, description="Maximum clubs allowed in trial")
    trial_duration_days: int = Field(default=30, description="Trial period duration")
    refund_period_days: int = Field(default=7, description="Refund eligibility period")
    groups_per_week: int = Field(default=1, description="Groups accessible per week")


class TrialMembershipStatus(BaseModel):
    is_trial_user: bool = Field(default=False)
    trial_start_date: Optional[datetime] = None
    trial_end_date: Optional[datetime] = None
    clubs_joined_count: int = Field(default=0, description="Clubs joined during trial")
    clubs_remaining: int = Field(default=4, description="Clubs still available to join")
    days_remaining: int = Field(default=0, description="Days left in trial")
    is_trial_active: bool = Field(default=False)
    is_refund_eligible: bool = Field(default=False)
    refund_deadline: Optional[datetime] = None


class ClubJoinRequest(BaseModel):
    club_id: str = Field(..., description="Club ID to join")
    pricing_plan: PricingPlan = Field(..., description="Selected pricing plan")
    payment_method_id: Optional[str] = Field(
        None, description="Stripe payment method ID for paid users"
    )


class ClubJoinResponse(BaseModel):
    success: bool
    message: str
    membership_info: Optional[MembershipInfo] = None
    payment_required: bool = Field(default=False)
    payment_intent_id: Optional[str] = None
    trial_status: Optional[TrialMembershipStatus] = None


# New models for join-trial-free API
class JoinTrialFreeRequest(BaseModel):
    """Request model for joining a club with trial membership"""

    club_id: str = Field(..., description="Club name-based ID to join")


class TrialClubAccess(BaseModel):
    """Model for tracking individual club access during trial"""

    club_id: str = Field(..., description="Club ID")
    club_name: str = Field(..., description="Club name")
    club_name_based_id: str = Field(..., description="Club name-based ID")
    captain_name: str = Field(..., description="Captain's name")
    join_date: datetime = Field(..., description="Date when club was joined")
    access_expires_date: datetime = Field(
        ..., description="Date when access expires (7 days from join)"
    )
    is_access_active: bool = Field(
        default=True, description="Whether access is currently active"
    )


class JoinTrialFreeResponse(BaseModel):
    """Response model for join-trial-free API"""

    success: bool = Field(..., description="Whether the join was successful")
    message: str = Field(..., description="Response message")
    club_access: Optional[TrialClubAccess] = Field(
        None, description="Details of the joined club"
    )
    trial_status: TrialMembershipStatus = Field(
        ..., description="Current trial membership status"
    )
    clubs_joined: List[TrialClubAccess] = Field(
        default=[], description="All clubs joined during trial"
    )
    can_join_more: bool = Field(..., description="Whether user can join more clubs")
    days_remaining_in_trial: int = Field(
        ..., description="Days remaining in trial period"
    )


# Enhanced member information models
class ClubMemberDetails(BaseModel):
    """Detailed member information stored in clubs collection"""

    user_id: str = Field(..., description="User's ID")
    full_name: str = Field(..., description="Member's full name")
    email: str = Field(..., description="Member's email address")
    phone: Optional[str] = Field(None, description="Member's phone number")
    avatar_url: Optional[str] = Field(None, description="Member's avatar URL")
    membership_type: str = Field(..., description="Type of membership (trial, paid)")
    membership_status: str = Field(
        ..., description="Status of membership (active, expired, cancelled)"
    )
    pricing_plan: str = Field(
        ..., description="Pricing plan (monthly, quarterly, yearly, trial)"
    )
    join_date: datetime = Field(..., description="Date when member joined the club")
    end_date: Optional[datetime] = Field(None, description="Date when membership ends")
    is_trial: bool = Field(
        default=False, description="Whether this is a trial membership"
    )
    is_active: bool = Field(
        default=True, description="Whether member is currently active"
    )
    last_seen: Optional[datetime] = Field(
        None, description="Last time member was active"
    )
    payment_id: Optional[str] = Field(None, description="Payment ID if paid membership")
    amount_paid: float = Field(default=0.0, description="Amount paid for membership")
    created_at: datetime = Field(
        ..., description="When this membership record was created"
    )
    updated_at: datetime = Field(
        ..., description="When this membership record was last updated"
    )


class UserClubDetails(BaseModel):
    """Club details stored in users collection"""

    club_id: str = Field(..., description="Club's ID")
    club_name: str = Field(..., description="Club's name")
    club_name_based_id: str = Field(..., description="Club's name-based ID")
    captain_name: str = Field(..., description="Captain's name")
    membership_type: str = Field(..., description="Type of membership (trial, paid)")
    membership_status: str = Field(
        ..., description="Status of membership (active, expired, cancelled)"
    )
    pricing_plan: str = Field(
        ..., description="Pricing plan (monthly, quarterly, yearly, trial)"
    )
    join_date: datetime = Field(..., description="Date when user joined the club")
    end_date: Optional[datetime] = Field(None, description="Date when membership ends")
    is_trial: bool = Field(
        default=False, description="Whether this is a trial membership"
    )
    is_active: bool = Field(
        default=True, description="Whether membership is currently active"
    )
    payment_id: Optional[str] = Field(None, description="Payment ID if paid membership")
    amount_paid: float = Field(default=0.0, description="Amount paid for membership")
    created_at: datetime = Field(
        ..., description="When this membership record was created"
    )
    updated_at: datetime = Field(
        ..., description="When this membership record was last updated"
    )


# My Club Detail API Models
class ModeratorDetail(BaseModel):
    """Moderator information"""

    email: str = Field(..., description="Email of the moderator")
    full_name: Optional[str] = Field(None, description="Full name of the moderator")


class CaptainDetail(BaseModel):
    """Captain information"""

    captain_id: str = Field(..., description="Captain's ID")
    captain_name: str = Field(..., description="Captain's full name")
    captain_name_based_id: Optional[str] = Field(
        None, description="Captain's name-based ID"
    )


class HubContentItem(BaseModel):
    """Individual hub content item"""

    hub_id: str = Field(..., description="Hub entry ID")
    title: str = Field(..., description="Title of the hub entry")
    description: Optional[str] = Field(None, description="Description of the hub entry")
    resource_url: str = Field(..., description="URL to the resource")
    platform: Optional[str] = Field(
        None, description="Platform where the resource is hosted"
    )
    club_id: str = Field(..., description="Club ID")
    club_name_based_id: str = Field(..., description="Club's name-based ID")
    hub_name_based_id: str = Field(..., description="Hub's name-based ID")
    captain_id: str = Field(..., description="Captain's ID")
    captain_name: str = Field(..., description="Captain's name")
    created_at: datetime = Field(..., description="Creation timestamp")
    duration: Optional[str] = Field(None, description="Duration of the content")
    section: str = Field(..., description="Section category")
    thumbnail: Optional[str] = Field(None, description="Thumbnail URL")
    is_active: bool = Field(..., description="Whether the hub entry is active")


class HubContentSummary(BaseModel):
    """Hub content summary for the club"""

    strategy_videos: List[HubContentItem] = Field(
        default_factory=list, description="Strategy video entries"
    )
    training_videos: List[HubContentItem] = Field(
        default_factory=list, description="Training video entries"
    )
    partner_links: List[HubContentItem] = Field(
        default_factory=list, description="Partner link entries"
    )
    strategy_videos_count: int = Field(
        default=0, description="Number of strategy videos"
    )
    training_videos_count: int = Field(
        default=0, description="Number of training videos"
    )
    partner_links_count: int = Field(default=0, description="Number of partner links")
    total_content: int = Field(default=0, description="Total hub content count")


class SportInfo(BaseModel):
    """Sport information with name and icon"""

    name: str = Field(..., description="Name of the sport")
    icon: Optional[str] = Field(None, description="Icon for the sport")


class BettingStats(BaseModel):
    """Betting statistics for a club"""

    total_bets: int = Field(default=0, description="Total number of completed bets")
    total_wins: int = Field(default=0, description="Total number of wins")
    total_losses: int = Field(default=0, description="Total number of losses")
    win_pct: float = Field(default=0.0, description="Win percentage")
    loss_pct: float = Field(default=0.0, description="Loss percentage")
    total_spread: int = Field(default=0, description="Total spread bets")
    total_over_under: int = Field(default=0, description="Total over/under bets")
    total_moneyline: int = Field(default=0, description="Total moneyline bets")
    total_parlay: int = Field(default=0, description="Total parlay bets")


class MyClubDetailResponse(BaseModel):
    """Response model for my-club-detail API"""

    club_id: str = Field(..., description="Unique ID of the club")
    club_name: str = Field(..., description="Name of the club")
    name_based_id: str = Field(..., description="Name-based ID of the club (slug)")
    created_at: datetime = Field(..., description="Creation timestamp of the club")
    status: str = Field(..., description="Current status of the club")
    description: Optional[str] = Field(None, description="Description of the club")
    sub_description: Optional[str] = Field(
        None, description="Sub-description of the club"
    )
    member_join_date: Optional[datetime] = Field(
        None, description="Date when the current member joined this club"
    )
    member_end_date: Optional[datetime] = Field(
        None, description="Date when the current member's access to this club ends"
    )
    moderator_details: List[ModeratorDetail] = Field(
        default_factory=list, description="Details of the club's moderators"
    )
    top_3_sports: List[SportInfo] = Field(
        default_factory=list, description="Top 3 sports for the club"
    )
    member_count: int = Field(
        default=0, description="Total number of members in the club"
    )
    # Betting statistics
    betting_stats: BettingStats = Field(default_factory=lambda: BettingStats(), description="Detailed betting statistics")
    total_bets: int = Field(default=0, description="Total number of bets (for backward compatibility)")
    win_pct: float = Field(default=0.0, description="Win percentage (for backward compatibility)")
    loss_pct: float = Field(default=0.0, description="Loss percentage")
    captain_details: CaptainDetail = Field(..., description="Captain information")
    hub_content: HubContentSummary = Field(..., description="Hub content summary")
    # Trial club statistics
    clubs_joined_count: int = Field(
        default=0, description="Number of clubs the user has joined"
    )
    clubs_remaining: int = Field(
        default=0, description="Number of clubs remaining in trial period"
    )
    max_clubs: int = Field(
        default=4, description="Maximum number of clubs allowed during trial period"
    )
    # Club rejection information
    rejection_type: Optional[str] = Field(
        None, description="Type of rejection (temporary/permanent)"
    )
    rejection_reason: Optional[str] = Field(
        None, description="Reason for club rejection"
    )
    rejected_by: Optional[str] = Field(None, description="Admin who rejected the club")
    is_resubmit: Optional[bool] = Field(
        None, description="Whether club can be resubmitted"
    )
    is_club_reject_temporary: Optional[bool] = Field(
        None, description="Whether club was temporarily rejected"
    )
    is_club_reject_permanently: Optional[bool] = Field(
        None, description="Whether club was permanently rejected"
    )
    user_role: str = Field(..., description="User's role in this club (Member, Moderator, Captain)")


class ModeratorClubDetailResponse(BaseModel):
    """Response model for moderator my-club-detail API (without hub content)"""

    club_id: str = Field(..., description="Unique ID of the club")
    club_name: str = Field(..., description="Name of the club")
    name_based_id: str = Field(..., description="Name-based ID of the club (slug)")
    created_at: datetime = Field(..., description="Creation timestamp of the club")
    status: str = Field(..., description="Current status of the club")
    description: Optional[str] = Field(None, description="Description of the club")
    sub_description: Optional[str] = Field(
        None, description="Sub-description of the club"
    )
    member_join_date: Optional[datetime] = Field(
        None, description="Date when the moderator joined this club"
    )
    member_end_date: Optional[datetime] = Field(
        None,
        description="Date when the moderator's access to this club ends (null for moderators)",
    )
    moderator_details: List[ModeratorDetail] = Field(
        default_factory=list,
        description="Details of other club moderators (excluding current moderator)",
    )
    top_3_sports: List[SportInfo] = Field(
        default_factory=list, description="Top 3 sports for the club"
    )
    member_count: int = Field(
        default=0, description="Total number of members in the club"
    )
    total_bets: int = Field(default=0, description="Total number of bets")
    win_pct: float = Field(default=0.0, description="Win percentage")
    captain_details: CaptainDetail = Field(..., description="Captain information")
    # Trial club statistics (not applicable for moderators, but included for consistency)
    clubs_joined_count: int = Field(
        default=0, description="Number of clubs the moderator has joined"
    )
    clubs_remaining: int = Field(
        default=0, description="Number of clubs remaining in trial period"
    )
    max_clubs: int = Field(
        default=0, description="Maximum number of clubs allowed during trial period"
    )
    # Club rejection information
    rejection_type: Optional[str] = Field(
        None, description="Type of rejection if club was rejected"
    )
    rejection_reason: Optional[str] = Field(
        None, description="Reason for rejection if club was rejected"
    )
    rejected_by: Optional[str] = Field(
        None, description="ID of the admin who rejected the club"
    )
    is_resubmit: Optional[bool] = Field(
        None, description="Whether the club can be resubmitted after rejection"
    )
    is_club_reject_temporary: Optional[bool] = Field(
        None, description="Whether the club rejection is temporary"
    )
    is_club_reject_permanently: Optional[bool] = Field(
        None, description="Whether the club rejection is permanent"
    )
    user_role: str = Field(..., description="User's role in this club (Member, Moderator, Captain)")

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper datetime and enum serialization"""
        data = super().model_dump(*args, **kwargs)
        # Convert datetime objects to ISO format strings
        if isinstance(data.get("created_at"), datetime):
            data["created_at"] = data["created_at"].isoformat()
        if isinstance(data.get("member_join_date"), datetime):
            data["member_join_date"] = data["member_join_date"].isoformat()
        if isinstance(data.get("member_end_date"), datetime):
            data["member_end_date"] = data["member_end_date"].isoformat()
        return data

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class WhatsIncludedItem(BaseModel):
    """What's included item with title and other details"""

    title: str = Field(..., description="Title of the included item")
    sub_desc: Optional[str] = Field(
        None, description="Sub-description of the included item"
    )
    logo_url: Optional[str] = Field(None, description="Logo URL for the included item")


class CaptainClubDetailResponse(BaseModel):
    """Response model for captain's club detail API"""

    club_id: str = Field(..., description="Unique ID of the club")
    club_name: str = Field(..., description="Name of the club")
    name_based_id: str = Field(..., description="Name-based ID of the club (slug)")
    created_at: datetime = Field(..., description="Creation timestamp of the club")
    status: str = Field(..., description="Current status of the club")
    description: Optional[str] = Field(None, description="Description of the club")
    sub_description: Optional[str] = Field(
        None, description="Sub-description of the club"
    )
    logo_url: Optional[str] = Field(None, description="URL of the club's logo")
    banner_url: Optional[str] = Field(None, description="URL of the club's banner")
    pricing_plan: Optional[str] = Field(None, description="Pricing plan for the club")
    pricing_plans: Optional[List[Dict]] = Field(
        None, description="Full pricing plans array with frequency, price, and currency"
    )
    total_bets: int = Field(default=0, description="Total number of bets")
    win_pct: float = Field(default=0.0, description="Win percentage")
    loss_pct: float = Field(default=0.0, description="Loss percentage")
    total_wins: int = Field(default=0, description="Total number of winning bets")
    total_losses: int = Field(default=0, description="Total number of losing bets")
    total_spread: int = Field(default=0, description="Total number of spread bets")
    total_over_under: int = Field(
        default=0, description="Total number of over/under bets"
    )
    total_moneyline: int = Field(
        default=0, description="Total number of moneyline bets"
    )
    total_parlay: int = Field(default=0, description="Total number of parlay bets")
    pick_types: List[str] = Field(
        default_factory=list, description="List of unique pick types submitted by captain in this club"
    )
    pick_type_counts: Dict[str, int] = Field(
        default_factory=dict, description="Count of bets for each pick type (e.g., {'Spread': 100, 'Parlay': 5, 'Prop': 20})"
    )
    whats_included: List[WhatsIncludedItem] = Field(
        default_factory=list, description="What's included in the club"
    )
    top_3_sports: List[SportInfo] = Field(
        default_factory=list, description="Top 3 sports for the club"
    )
    total_revenue: float = Field(default=0.0, description="Total revenue generated")
    member_count: int = Field(
        default=0, description="Total number of members in the club"
    )
    active_members_count: int = Field(
        default=0, description="Number of active members in the club"
    )
    inactive_members_count: int = Field(
        default=0, description="Number of inactive members in the club"
    )
    total_moderators: int = Field(default=0, description="Total number of moderators")
    captain_id: str = Field(..., description="Captain's ID")
    captain_full_name: str = Field(..., description="Captain's full name")
    captain_name_based_id: Optional[str] = Field(
        None, description="Captain's name-based ID"
    )
    # User role in this specific club
    user_role: Optional[str] = Field(
        None, description="User's role in this club (Captain/Member/Moderator)"
    )
    # Club rejection information
    rejection_type: Optional[str] = Field(
        None, description="Type of rejection (temporary/permanent)"
    )
    rejection_reason: Optional[str] = Field(
        None, description="Reason for club rejection"
    )
    rejected_by: Optional[str] = Field(None, description="Admin who rejected the club")
    is_resubmit: Optional[bool] = Field(
        None, description="Whether club can be resubmitted"
    )
    is_club_reject_temporary: Optional[bool] = Field(
        None, description="Whether club was temporarily rejected"
    )
    is_club_reject_permanently: Optional[bool] = Field(
        None, description="Whether club was permanently rejected"
    )


class RefundRequest(BaseModel):
    reason: str = Field(
        ..., min_length=10, max_length=500, description="Reason for refund"
    )
    club_ids: Optional[List[str]] = Field(
        None, description="Specific clubs to refund, if None then all trial memberships"
    )


class RefundResponse(BaseModel):
    success: bool
    message: str
    refund_amount: float = Field(default=0.0)
    refunded_memberships: List[str] = Field(default=[])
    refund_id: Optional[str] = None


class TrialStatusResponse(BaseModel):
    trial_status: TrialMembershipStatus
    joined_clubs: List[ClubResponse] = Field(default=[])
    available_actions: List[str] = Field(default=[])
    limits: TrialLimits


class GroupAccessInfo(BaseModel):
    groups_accessed_this_week: int = Field(default=0)
    groups_remaining_this_week: int = Field(default=1)
    next_reset_date: datetime
    can_access_groups: bool = Field(default=True)


# Database models for trial tracking
class TrialMembershipDocument(BaseModel):
    """Trial membership tracking document"""

    user_id: str
    trial_start_date: datetime
    trial_end_date: datetime
    clubs_joined: List[str] = Field(default=[])
    refund_requested: bool = Field(default=False)
    refund_processed: bool = Field(default=False)
    refund_amount: float = Field(default=0.0)
    refund_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class GroupAccessDocument(BaseModel):
    """Group access tracking for trial users"""

    user_id: str
    week_start_date: datetime
    groups_accessed: int = Field(default=0)
    last_access_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# Updated ClubMembershipDocument to include trial info
class ClubMembershipDocument(BaseModel):
    """Internal model for club membership tracking"""

    user_id: str
    club_id: str
    pricing_plan: str  # monthly, quarterly, yearly
    subscription_status: str  # active, expired, cancelled, pending, trial
    is_trial_membership: bool = Field(default=False)
    trial_join_date: Optional[datetime] = None
    joined_date: datetime
    expires_date: Optional[datetime] = None
    payment_id: Optional[str] = None
    amount_paid: float = Field(default=0.0)
    refund_eligible: bool = Field(default=False)
    refund_deadline: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# Ongoing Membership Models
class OngoingMembershipCaptain(BaseModel):
    captain_id: str
    captain_name: str
    captain_profile_pic: Optional[str] = None


class OngoingMembershipDetails(BaseModel):
    club_id: str
    club_name: str
    club_logo: Optional[str] = None
    captain: OngoingMembershipCaptain
    membership_type: str = Field(..., description="trial or paid")
    start_date: datetime
    next_renewal_date: Optional[datetime] = None
    price: float = Field(default=0.0, description="Membership price (0 for trial)")
    pricing_plan: str = Field(..., description="monthly, quarterly, yearly, or trial")
    currency: str = Field(default="USD")
    status: str = Field(..., description="Active, Paused, Cancelled, or Trial")
    days_remaining: Optional[int] = None
    auto_renewal: bool = Field(default=True)
    can_cancel: bool = Field(default=True)
    can_upgrade: bool = Field(default=False, description="For trial memberships")


class OngoingMembershipsResponse(BaseModel):
    memberships: List[OngoingMembershipDetails]
    total_count: int
    active_count: int
    trial_count: int
    paid_count: int
    total_monthly_cost: float = Field(
        default=0.0, description="Total monthly cost of all paid memberships"
    )


class MembershipSummary(BaseModel):
    """Summary of user's membership status"""

    is_trial_user: bool
    total_memberships: int
    active_memberships: int
    trial_memberships: int
    paid_memberships: int
    monthly_cost: float
    next_renewal: Optional[datetime] = None
    trial_days_remaining: Optional[int] = None


# Past Membership Models
class PastMembershipDetails(BaseModel):
    club_id: str
    club_name: str
    club_logo_url: Optional[str] = None
    captain_name: str
    captain_image_url: Optional[str] = None
    membership_type: str = Field(..., description="trial or paid")
    price: Optional[str] = None  # e.g., "$14.99/month" or None for trial
    start_date: datetime
    end_date: datetime
    status: str = Field(..., description="expired, canceled, or trial_expired")


class PastMembershipsResponse(BaseModel):
    past_memberships: List[PastMembershipDetails]
    total_count: int
    trial_count: int = Field(default=0, description="Number of past trial memberships")
    paid_count: int = Field(default=0, description="Number of past paid memberships")
    canceled_count: int = Field(
        default=0, description="Number of manually canceled memberships"
    )
    expired_count: int = Field(
        default=0, description="Number of naturally expired memberships"
    )


class MembershipHistorySummary(BaseModel):
    """Complete membership history summary"""

    total_past_memberships: int
    total_ongoing_memberships: int
    clubs_tried: int = Field(description="Unique clubs the user has been a member of")
    total_spent: float = Field(
        default=0.0, description="Total amount spent on memberships"
    )
    favorite_club: Optional[str] = None
    most_recent_activity: Optional[datetime] = None


# Enhanced Pricing Models with Stripe Integration
class StripePricingPlan(BaseModel):
    plan: PricingPlan
    price: float = Field(..., gt=0, description="Price must be greater than 0")
    currency: str = Field(default="USD", description="Currency code")
    stripe_product_id: Optional[str] = None
    stripe_price_id: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ClubPricingPlansRequest(BaseModel):
    club_id: str
    pricing_plans: List[StripePricingPlan] = Field(
        ..., min_items=1, description="At least one pricing plan required"
    )

    @field_validator("pricing_plans")
    @classmethod
    def validate_pricing_plans(cls, v):
        if not v:
            raise ValueError("At least one pricing plan is required")

        # Check for duplicate plans
        plans = [plan.plan for plan in v]
        if len(plans) != len(set(plans)):
            raise ValueError("Duplicate pricing plans are not allowed")

        return v


class ClubPricingPlansResponse(BaseModel):
    success: bool
    message: str
    club_id: str
    pricing_plans: List[StripePricingPlan]


class ClubMembershipPaymentRequest(BaseModel):
    club_id: str
    pricing_plan: PricingPlan
    payment_method_id: str


class ClubMembershipPaymentResponse(BaseModel):
    success: bool
    message: str
    subscription_id: Optional[str] = None
    customer_id: Optional[str] = None
    price_id: Optional[str] = None
    membership_id: Optional[str] = None
    payment_status: Optional[str] = None


class WebhookEventData(BaseModel):
    """Model for Stripe webhook events"""

    event_type: str
    subscription_id: Optional[str] = None
    customer_id: Optional[str] = None
    payment_intent_id: Optional[str] = None
    invoice_id: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    metadata: Optional[dict] = None


# Image Upload Models
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


class ImageUploadError(BaseModel):
    """Error model for image upload failures"""

    success: bool
    message: str
    error_code: str
    details: Optional[str] = None


class ImageMetadata(BaseModel):
    """Metadata for uploaded images"""

    original_filename: str
    file_size_bytes: int
    content_type: str
    dimensions: Optional[dict] = None  # width, height
    uploaded_by: str
    upload_purpose: str = Field(
        ..., description="Purpose: club_logo, club_banner, user_avatar, etc."
    )
    club_id: Optional[str] = None
    user_id: Optional[str] = None


# ============================================================================
# CLUB STEP 1 MODELS
# ============================================================================


class ClubStatus(str, Enum):
    """Club approval status"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INACTIVE = "inactive"


class ClubStep1CreateRequest(BaseModel):
    """Request model for creating club step 1"""

    name: str = Field(..., min_length=3, max_length=100, description="Club name")
    description: str = Field(
        ..., min_length=10, max_length=500, description="Club description"
    )
    sub_description: Optional[str] = Field(
        None,
        min_length=5,
        max_length=200,
        description="Short subtitle or tagline for the club",
    )
    logo_url: Optional[str] = Field(None, description="URL to club logo/image")
    banner_url: Optional[str] = Field(None, description="URL to club banner image")
    name_based_id: str = Field(..., description="URL-friendly ID based on club name")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Club name cannot be empty")
        return v.strip()


class ClubStep1Response(BaseModel):
    """Response model for club step 1"""

    id: str = Field(..., description="Club ID")
    name: str = Field(..., description="Club name")
    name_based_id: str = Field(..., description="URL-friendly ID based on club name")
    description: str = Field(..., description="Club description")
    sub_description: Optional[str] = Field(
        None, description="Short subtitle or tagline for the club"
    )
    logo_url: Optional[str] = Field(None, description="URL to club logo/image")
    banner_url: Optional[str] = Field(None, description="URL to club banner image")
    status: ClubStatus = Field(..., description="Club approval status")
    club_complete_step: int = Field(
        ..., description="Current completion step (1 for step 1)"
    )
    captain_id: str = Field(..., description="Captain ID who created the club")
    captain: dict = Field(
        ..., description="Captain details including id, full_name, and name_based_id"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper datetime and enum serialization"""
        data = super().model_dump(*args, **kwargs)
        # Convert datetime objects to ISO format strings
        if isinstance(data.get("created_at"), datetime):
            data["created_at"] = data["created_at"].isoformat()
        if isinstance(data.get("updated_at"), datetime):
            data["updated_at"] = data["updated_at"].isoformat()
        # Ensure enum values are strings
        if isinstance(data.get("status"), ClubStatus):
            data["status"] = data["status"].value
        return data

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            ClubStatus: lambda v: v.value,
        }


class ClubStep1Document(BaseModel):
    """Database document model for club step 1"""

    name: str
    name_based_id: str = Field(..., description="URL-friendly ID based on club name")
    description: str
    sub_description: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    status: ClubStatus = Field(default=ClubStatus.PENDING)
    club_complete_step: int = Field(default=1)
    captain_id: str
    captain_details: dict = Field(
        ..., description="Captain details including id, full_name, and name_based_id"
    )
    created_at: datetime
    updated_at: datetime

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper enum and datetime serialization"""
        data = super().model_dump(*args, **kwargs)
        # Ensure enum values are strings
        if isinstance(data.get("status"), ClubStatus):
            data["status"] = data["status"].value
        return data

    class Config:
        json_encoders = {ClubStatus: lambda v: v.value}


# ============================================================================
# CLUB STEP 2 MODELS (What's Included + Top 3 Sports)
# ============================================================================


class ClubInclusionSelection(BaseModel):
    """Model for selected inclusion"""

    title: str = Field(..., description="Inclusion title")
    sub_desc: str = Field(..., description="Inclusion description")
    logo_url: Optional[str] = Field(None, description="URL to inclusion logo/icon")


class ClubSportSelection(BaseModel):
    """Model for selected sport"""

    name: str = Field(..., description="Sport name")
    icon: str = Field(..., description="Sport icon")


# New simplified models for step 2 API
class ClubInclusionTitleRequest(BaseModel):
    """Simplified model for inclusion selection - only title required"""

    title: str = Field(..., description="Inclusion title to fetch from admin database")


class ClubSportNameRequest(BaseModel):
    """Simplified model for sport selection - only name required"""

    name: str = Field(..., description="Sport name to fetch from admin database")


class ClubStep2UpdateRequest(BaseModel):
    """Request model for updating club step 2"""

    club_id: str = Field(..., description="Club ID to update")
    whats_included: List[ClubInclusionSelection] = Field(
        ...,
        min_items=1,
        max_items=10,
        description="Selected inclusions from admin database",
    )
    top_3_sports: List[ClubSportSelection] = Field(
        ...,
        min_items=1,
        max_items=3,
        description="Top 3 selected sports from admin database",
    )


# New simplified request model for step 2 API
class ClubStep2UpdateSimpleRequest(BaseModel):
    """Simplified request model for updating club step 2 - only titles and names required"""

    club_id: str = Field(..., description="Club ID to update")
    whats_included: List[ClubInclusionTitleRequest] = Field(
        ...,
        min_items=1,
        max_items=10,
        description="Selected inclusion titles to fetch from admin database",
    )
    top_3_sports: List[ClubSportNameRequest] = Field(
        ...,
        min_items=1,
        max_items=3,
        description="Selected sport names to fetch from admin database",
    )


class ClubStep2Response(BaseModel):
    """Response model for club step 2 update"""

    id: str = Field(..., description="Club ID")
    name: str = Field(..., description="Club name")
    name_based_id: str = Field(..., description="URL-friendly ID based on club name")
    description: str = Field(..., description="Club description")
    sub_description: Optional[str] = Field(
        None, description="Short subtitle or tagline for the club"
    )
    logo_url: Optional[str] = Field(None, description="URL to club logo/image")
    status: ClubStatus = Field(..., description="Club approval status")
    club_complete_step: int = Field(
        ..., description="Current completion step (2 for step 2)"
    )
    captain_id: str = Field(..., description="Captain ID who created the club")
    whats_included: List[ClubInclusionSelection] = Field(
        ..., description="Selected inclusions"
    )
    top_3_sports: List[ClubSportSelection] = Field(
        ..., description="Top 3 selected sports"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
            ObjectId: lambda oid: str(oid),
            ClubStatus: lambda status_enum: status_enum.value,
        }
        populate_by_name = True
        arbitrary_types_allowed = True

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper enum and datetime serialization"""
        data = super().model_dump(*args, **kwargs)
        # Ensure enum values are strings
        if isinstance(data.get("status"), ClubStatus):
            data["status"] = data["status"].value
        # Ensure datetime objects are ISO formatted strings
        if isinstance(data.get("created_at"), datetime):
            data["created_at"] = data["created_at"].isoformat()
        if isinstance(data.get("updated_at"), datetime):
            data["updated_at"] = data["updated_at"].isoformat()
        return data


class ClubStep2Document(BaseModel):
    """Database document model for club step 2"""

    whats_included: List[ClubInclusionSelection]
    top_3_sports: List[ClubSportSelection]
    club_complete_step: int = Field(2, description="Step 2 completion")
    updated_at: datetime = Field(..., description="Last update timestamp")

    def model_dump(self, *args, **kwargs):
        """Convert to dict for MongoDB update"""
        data = super().model_dump(*args, **kwargs)
        # Keep datetime objects as-is for MongoDB
        return data


# ============================================================================
# CLUB STEP 3 MODELS (Pricing Setup)
# ============================================================================


class ClubPricingPlan(BaseModel):
    """Model for individual pricing plan"""

    frequency: PricingPlan = Field(
        ...,
        description="Pricing frequency (daily, weekly, monthly, quarterly, yearly, lifetime)",
    )
    price: float = Field(..., gt=0, description="Price must be greater than 0")
    currency: str = Field(default="USD", description="Currency code")
    stripe_product_id: Optional[str] = Field(None, description="Stripe product ID")
    stripe_price_id: Optional[str] = Field(None, description="Stripe price ID")


class ClubStep3UpdateRequest(BaseModel):
    """Request model for updating club step 3 (pricing setup)"""

    club_id: str = Field(..., description="Club ID to update")
    pricing_plans: List[ClubPricingPlan] = Field(
        ...,
        min_items=1,
        description="Pricing plans (daily, weekly, monthly, quarterly, yearly, lifetime)",
    )


class ClubStep3Response(BaseModel):
    """Response model for club step 3 update"""

    id: str = Field(..., description="Club ID")
    name: str = Field(..., description="Club name")
    name_based_id: str = Field(..., description="URL-friendly ID based on club name")
    description: str = Field(..., description="Club description")
    sub_description: Optional[str] = Field(
        None, description="Short subtitle or tagline for the club"
    )
    logo_url: Optional[str] = Field(None, description="URL to club logo/image")
    status: ClubStatus = Field(..., description="Club approval status")
    club_complete_step: int = Field(
        ..., description="Current completion step (3 for step 3)"
    )
    captain_id: str = Field(..., description="Captain ID who created the club")
    whats_included: List[ClubInclusionSelection] = Field(
        ..., description="Selected inclusions"
    )
    top_3_sports: List[ClubSportSelection] = Field(
        ..., description="Top 3 selected sports"
    )
    pricing_plans: List[ClubPricingPlan] = Field(..., description="Pricing plans")
    has_stripe_product: bool = Field(
        False, description="Whether club has Stripe product created"
    )
    has_stripe_price: bool = Field(
        False, description="Whether club has Stripe prices created"
    )
    stripe_product_id: Optional[str] = Field(
        None, description="Stripe product ID for the club"
    )
    total_plans: int = Field(0, description="Total number of pricing plans")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper enum and datetime serialization"""
        data = super().model_dump(*args, **kwargs)
        # Ensure enum values are strings
        if isinstance(data.get("status"), ClubStatus):
            data["status"] = data["status"].value
        # Ensure datetime objects are ISO formatted strings
        if isinstance(data.get("created_at"), datetime):
            data["created_at"] = data["created_at"].isoformat()
        if isinstance(data.get("updated_at"), datetime):
            data["updated_at"] = data["updated_at"].isoformat()
        return data


class ClubStep3Document(BaseModel):
    """Database document model for club step 3"""

    pricing_plans: List[ClubPricingPlan]
    club_complete_step: int = Field(3, description="Step 3 completion")
    updated_at: datetime = Field(..., description="Last update timestamp")

    def model_dump(self, *args, **kwargs):
        """Convert to dict for MongoDB update"""
        data = super().model_dump(*args, **kwargs)
        # Keep datetime objects as-is for MongoDB
        return data


# ============================================================================
# CLUB STEP 4 MODELS (Moderator Setup)
# ============================================================================


class ModeratorStatus(str, Enum):
    """Status of moderator invitation"""

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class ModeratorInvitation(BaseModel):
    """Model for moderator invitation"""

    email: str = Field(..., description="Moderator email address")
    user_id: str = Field(..., description="User ID of the moderator")
    name: str = Field(..., description="Moderator name")
    status: ModeratorStatus = Field(..., description="Invitation status")
    invited_at: datetime = Field(..., description="When invitation was sent")
    responded_at: Optional[datetime] = Field(
        None, description="When moderator responded"
    )
    response: Optional[str] = Field(None, description="Response: 'accept' or 'decline'")


class DetailedModeratorInfo(BaseModel):
    """Model for detailed moderator information stored in database"""

    email: str = Field(..., description="Moderator email address")
    full_name: str = Field(..., description="Moderator's full name")
    user_id: str = Field(..., description="User ID of the moderator")
    status: str = Field(..., description="Moderator status (active, inactive, pending)")
    type_of_moderator: str = Field(..., description="Type of moderator (free, paid)")
    price: float = Field(
        ..., description="Price for this moderator (0 for free, 9.95 for paid)"
    )
    invited_at: datetime = Field(..., description="When invitation was sent")
    responded_at: Optional[datetime] = Field(
        None, description="When moderator responded"
    )
    response: Optional[str] = Field(None, description="Response: 'accept' or 'decline'")


class ClubStep4UpdateRequest(BaseModel):
    """Request model for updating club step 4 (moderator setup)"""

    club_id: str = Field(..., description="Club ID to update")
    moderator_emails: Optional[List[str]] = Field(
        default=[], description="List of moderator email addresses (optional)"
    )


class ClubStep4Response(BaseModel):
    """Response model for club step 4 update"""

    id: str = Field(..., description="Club ID")
    name: str = Field(..., description="Club name")
    name_based_id: str = Field(..., description="URL-friendly ID based on club name")
    description: str = Field(..., description="Club description")
    sub_description: Optional[str] = Field(
        None, description="Short subtitle or tagline for the club"
    )
    logo_url: Optional[str] = Field(None, description="URL to club logo/image")
    status: ClubStatus = Field(..., description="Club approval status")
    club_complete_step: int = Field(
        ..., description="Current completion step (4 for step 4)"
    )
    captain_id: str = Field(..., description="Captain ID who created the club")
    moderator_emails: List[str] = Field(
        ..., description="List of moderator email addresses"
    )
    detailed_moderators: List[DetailedModeratorInfo] = Field(
        default=[], description="Detailed moderator information"
    )
    moderator_count: int = Field(..., description="Total number of moderators")
    free_moderators: int = Field(
        ..., description="Number of free moderators (first one)"
    )
    paid_moderators: int = Field(
        ..., description="Number of paid moderators (additional ones)"
    )
    additional_moderator_price: float = Field(
        ..., description="Price per additional moderator per month"
    )
    additional_moderator_currency: str = Field(
        ..., description="Currency for additional moderator pricing"
    )
    total_additional_moderator_pricing: float = Field(
        ...,
        description="Total cost for all paid moderators (paid_moderators * additional_moderator_price)",
    )
    stripe_product_id: Optional[str] = Field(
        None, description="Stripe product ID for moderator subscriptions"
    )
    stripe_price_id: Optional[str] = Field(
        None, description="Stripe price ID for moderator subscriptions"
    )
    moderator_invitations: List[ModeratorInvitation] = Field(
        ..., description="List of moderator invitations"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper enum and datetime serialization"""
        data = super().model_dump(*args, **kwargs)
        # Ensure enum values are strings
        if isinstance(data.get("status"), ModeratorStatus):
            data["status"] = data["status"].value
        # Ensure datetime objects are ISO formatted strings
        if isinstance(data.get("created_at"), datetime):
            data["created_at"] = data["created_at"].isoformat()
        if isinstance(data.get("updated_at"), datetime):
            data["updated_at"] = data["updated_at"].isoformat()
        return data


class ClubStep4Document(BaseModel):
    """Database document model for club step 4"""

    moderator_emails: List[str] = Field(
        ..., description="List of moderator email addresses"
    )
    detailed_moderators: List[DetailedModeratorInfo] = Field(
        default=[], description="Detailed moderator information"
    )
    moderator_count: int = Field(..., description="Total number of moderators")
    free_moderators: int = Field(
        ..., description="Number of free moderators (first one)"
    )
    paid_moderators: int = Field(
        ..., description="Number of paid moderators (additional ones)"
    )
    additional_moderator_price: float = Field(
        ..., description="Price per additional moderator per month"
    )
    additional_moderator_currency: str = Field(
        ..., description="Currency for additional moderator pricing"
    )
    total_additional_moderator_pricing: float = Field(
        ...,
        description="Total cost for all paid moderators (paid_moderators * additional_moderator_price)",
    )
    stripe_product_id: Optional[str] = Field(
        None, description="Stripe product ID for moderator subscriptions"
    )
    stripe_price_id: Optional[str] = Field(
        None, description="Stripe price ID for moderator subscriptions"
    )
    club_complete_step: int = Field(4, description="Step 4 completion")
    updated_at: datetime = Field(..., description="Last update timestamp")

    def model_dump(self, *args, **kwargs):
        """Convert to dict for MongoDB update"""
        data = super().model_dump(*args, **kwargs)
        # Keep datetime objects as-is for MongoDB
        return data


# ============================================================================
# MY-CLUBS API MODELS
# ============================================================================


class MyClubsSortOption(str, Enum):
    """Sort options for my-clubs API"""

    MOST_MEMBERS = "most_members"  # by member_count desc
    NEWEST = "newest"  # by created_at desc
    OLDEST = "oldest"  # by created_at asc


class MyClubsFilters(BaseModel):
    """Filters for my-clubs API"""

    search: Optional[str] = Field(
        None, description="Search by club name or captain name"
    )
    status: Optional[ClubStatus] = Field(None, description="Filter by club status")
    member_status: Optional[str] = Field(
        None,
        description="Filter by member status (active, inactive) - only works for members",
    )
    pricing_plan: Optional[PricingPlan] = Field(
        None, description="Filter by pricing plan"
    )


class MyClubItem(BaseModel):
    """Individual club item for my-clubs API response"""

    club_id: str = Field(..., description="Club ID")
    club_name: str = Field(..., description="Club name")
    name_based_id: str = Field(..., description="URL-friendly ID based on club name")
    created_at: datetime = Field(..., description="Club creation timestamp")
    status: ClubStatus = Field(..., description="Club approval status")
    pricing: Optional[Dict] = Field(
        None, description="Priority pricing plan with frequency, price, and currency"
    )
    pricing_plans: Optional[List[Dict]] = Field(
        None, description="Full pricing plans with frequency, price, and currency"
    )
    total_members: int = Field(default=0, description="Total members in the club")
    moderator_count: int = Field(default=0, description="Total moderators in the club")
    monthly_revenue: float = Field(default=0.0, description="Monthly revenue generated")
    total_revenue: Optional[float] = Field(None, description="Total revenue generated (captain's 95% share)")
    logo_url: Optional[str] = Field(None, description="URL to club logo/image")
    # Member-specific fields (only populated for members, not captains)
    member_status: Optional[str] = Field(
        None, description="Member's status in this club (active/inactive)"
    )
    membership_status: Optional[str] = Field(
        None, description="Member's membership status in this club (active/inactive)"
    )
    member_combined_status: Optional[str] = Field(
        None,
        description="Combined member status: active if both member_status and membership_status are active, inactive otherwise",
    )
    # User role in this specific club
    user_role: Optional[str] = Field(
        None, description="User's role in this club (Captain/Member/Moderator)"
    )
    # Club deletion/reactivation fields (only populated for captains)
    is_permanently_deleted: Optional[bool] = Field(
        None, description="Whether the club is permanently deleted"
    )
    is_temporarily_deleted: Optional[bool] = Field(
        None, description="Whether the club is temporarily deleted"
    )
    reactivated_at: Optional[datetime] = Field(
        None, description="When the club was reactivated (if applicable)"
    )
    reactivated_by: Optional[str] = Field(
        None, description="Who reactivated the club (if applicable)"
    )
    deletion_reason: Optional[str] = Field(
        None, description="Reason for club deletion (if applicable)"
    )
    deleted_at: Optional[datetime] = Field(
        None, description="When the club was deleted (if applicable)"
    )
    deleted_by: Optional[str] = Field(
        None, description="Who deleted the club (if applicable)"
    )
    # Chat status fields
    is_chat_open: Optional[bool] = Field(
        False, description="Whether user has this club's chat open (defaults to False)"
    )
    push_type: Optional[str] = Field(
        "", description="Push notification type: 'chat_message' for chat messages, '' for others"
    )

    def model_dump(self, *args, **kwargs):
        """Convert to dict with proper datetime and enum serialization"""
        data = super().model_dump(*args, **kwargs)
        # Convert datetime objects to ISO format strings
        if isinstance(data.get("created_at"), datetime):
            data["created_at"] = data["created_at"].isoformat()
        if isinstance(data.get("reactivated_at"), datetime):
            data["reactivated_at"] = data["reactivated_at"].isoformat()
        if isinstance(data.get("deleted_at"), datetime):
            data["deleted_at"] = data["deleted_at"].isoformat()
        # Ensure enum values are strings
        if isinstance(data.get("status"), ClubStatus):
            data["status"] = data["status"].value
        return data

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            ClubStatus: lambda v: v.value,
        }


class MyClubsResponse(BaseModel):
    """Response model for my-clubs API"""

    clubs: List[MyClubItem]
    total_count: int
    total_members: int = Field(default=0, description="Total members across all clubs")
    total_moderators: int = Field(default=0, description="Total moderators across all clubs")
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


# ============================================================================
# CLUB CONFIRMATION MODELS
# ============================================================================


class ClubConfirmationFreeRequest(BaseModel):
    """Request model for free club confirmation (no additional moderators)"""

    club_id: str = Field(
        ..., description="Club ID to confirm (can be ObjectId or name_based_id)"
    )


class ClubConfirmationFreeResponse(BaseModel):
    """Response model for free club confirmation"""

    club_id: str = Field(..., description="Club ID")
    club_name: str = Field(..., description="Club name")
    name_based_id: str = Field(..., description="URL-friendly ID based on club name")
    status: ClubStatus = Field(
        ..., description="Club status (should be 'pending' after confirmation)"
    )
    confirmation_type: str = Field(default="free", description="Type of confirmation")
    moderator_count: int = Field(..., description="Total number of moderators")
    free_moderators: int = Field(..., description="Number of free moderators")
    paid_moderators: int = Field(..., description="Number of paid moderators")
    total_additional_moderator_pricing: float = Field(
        ..., description="Total additional moderator pricing (should be 0.0 for free)"
    )
    confirmed_at: datetime = Field(..., description="Confirmation timestamp")
    club_complete_step: int = Field(
        ..., description="Club completion step (should be 5 after confirmation)"
    )


class ClubConfirmationPaidRequest(BaseModel):
    """Request model for paid club confirmation (with additional moderators)"""

    club_id: str = Field(
        ..., description="Club ID to confirm (can be ObjectId or name_based_id)"
    )
    email: str = Field(..., description="Captain's email for payment")
    payment_method_id: str = Field(..., description="Stripe payment method ID")
    price: float = Field(..., description="Expected price to pay")


class ClubConfirmationPaidResponse(BaseModel):
    """Response model for paid club confirmation"""

    club_id: str = Field(..., description="Club ID")
    club_name: str = Field(..., description="Club name")
    name_based_id: str = Field(..., description="URL-friendly ID based on club name")
    status: ClubStatus = Field(..., description="Club status")
    confirmation_type: str = Field(default="paid", description="Type of confirmation")
    moderator_count: int = Field(..., description="Total number of moderators")
    free_moderators: int = Field(..., description="Number of free moderators")
    paid_moderators: int = Field(..., description="Number of paid moderators")
    total_additional_moderator_pricing: float = Field(
        ..., description="Total additional moderator pricing"
    )
    payment_intent_id: Optional[str] = Field(
        None, description="Stripe payment intent ID"
    )
    payment_status: str = Field(..., description="Payment status")
    confirmed_at: Optional[datetime] = Field(
        None, description="Confirmation timestamp (set after successful payment)"
    )
    club_complete_step: int = Field(
        ..., description="Club completion step (should be 5 after confirmation)"
    )


# ============================================================================
# HUB MODELS
# ============================================================================


class HubSection(str, Enum):
    """Enum for hub section types"""

    STRATEGY_VIDEO = "strategy video"
    TRAINING_VIDEO = "training video"
    PARTNER_LINKS = "partner links"


class CreateHubRequest(BaseModel):
    """Request model for creating a hub entry"""

    title: str = Field(
        ..., min_length=1, max_length=200, description="Title of the hub entry"
    )
    description: Optional[str] = Field(
        None, max_length=1000, description="Description of the hub entry"
    )
    resource_url: HttpUrl = Field(..., description="URL to the resource (video/link)")
    platform: Optional[str] = Field(
        None, max_length=100, description="Platform where the resource is hosted"
    )
    club_id: str = Field(..., description="name_based_id of the club")
    duration: Optional[str] = Field(
        None, max_length=50, description="Duration of the video/content"
    )
    section: HubSection = Field(..., description="Section category for the hub entry")
    thumbnail: Optional[str] = Field(
        None, max_length=500, description="URL to the thumbnail image (optional)"
    )


class HubDocument(BaseModel):
    """Database document model for hub entries"""

    model_config = ConfigDict(
        populate_by_name=True, from_attributes=True, arbitrary_types_allowed=True
    )

    id: Optional[ObjectId] = Field(None, alias="_id")
    title: str
    description: Optional[str] = None
    resource_url: str
    platform: Optional[str] = None
    club_id: Optional[ObjectId] = Field(None, description="Club ID from database")
    club_name_based_id: str
    hub_name_based_id: str = Field(
        ..., description="URL-friendly ID based on hub title"
    )
    captain_id: str
    captain_name: str
    created_at: datetime
    duration: Optional[str] = None
    section: HubSection
    thumbnail: Optional[str] = None
    is_active: bool = True


class HubResponse(BaseModel):
    """Response model for hub entries"""

    model_config = ConfigDict(
        populate_by_name=True, from_attributes=True, arbitrary_types_allowed=True
    )

    hub_id: str = Field(..., alias="_id")
    title: str
    description: Optional[str] = None
    resource_url: str
    platform: Optional[str] = None
    club_id: str = Field(..., description="Club ID (converted to string)")
    club_name_based_id: str
    hub_name_based_id: str = Field(
        ..., description="URL-friendly ID based on hub title"
    )
    captain_id: str
    captain_name: str
    created_at: datetime
    duration: Optional[str] = None
    section: HubSection
    thumbnail: Optional[str] = None
    is_active: bool


class CreateHubResponse(BaseModel):
    """Response model for create-hub API"""

    status: str = "success"
    message: str = "Hub entry created successfully"
    data: HubResponse


class ErrorResponse(BaseModel):
    """Error response model"""

    status: str = "error"
    message: str
    error_code: Optional[str] = None


# ============================================================================
# HUB EDIT/DELETE MODELS
# ============================================================================


class EditHubRequest(BaseModel):
    """Request model for editing a hub entry"""

    title: Optional[str] = Field(
        None, min_length=1, max_length=200, description="Title of the hub entry"
    )
    description: Optional[str] = Field(
        None, min_length=1, max_length=1000, description="Description of the hub entry"
    )
    resource_url: Optional[HttpUrl] = Field(
        None, description="URL to the resource (video/link)"
    )
    platform: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Platform where the resource is hosted",
    )
    duration: Optional[str] = Field(
        None, max_length=50, description="Duration of the video/content"
    )
    section: HubSection = Field(
        ..., description="Section category for the hub entry (required)"
    )
    thumbnail: Optional[str] = Field(
        None, max_length=500, description="URL to the thumbnail image (optional)"
    )


class EditHubResponse(BaseModel):
    """Response model for edit-hub API"""

    status: str = "success"
    message: str = "Hub entry updated successfully"
    data: HubResponse


class DeleteHubResponse(BaseModel):
    """Response model for delete-hub API"""

    status: str = "success"
    message: str = "Hub entry deleted successfully"
    hub_id: str


# ============================================================================
# HUB FILTERING MODELS
# ============================================================================


class HubSortOption(str, Enum):
    """Enum for hub sorting options"""

    NEWEST = "newest"  # by created_at desc
    OLDEST = "oldest"  # by created_at asc
    A_TO_Z = "A-Z"  # by title asc


class HubSection(str, Enum):
    """Enum for hub section types"""

    STRATEGY_VIDEO = "strategy video"
    TRAINING_VIDEO = "training video"
    PARTNER_LINKS = "partner links"


# Note: HubFiltersRequest removed since we're now using query parameters
# The filtering is handled directly in the GET endpoint with Query parameters


class HubStatsResponse(BaseModel):
    """Response model for hub statistics API"""

    total_strategy_videos: int = Field(
        ..., description="Total number of strategy videos"
    )
    total_training_videos: int = Field(
        ..., description="Total number of training videos"
    )
    total_partner_links: int = Field(..., description="Total number of partner links")
    total_content: int = Field(
        ..., description="Total content (strategy + training + partner links)"
    )
    club_id: Optional[str] = Field(None, description="Club ID filter applied (if any)")
    club_name_based_id: Optional[str] = Field(
        None, description="Club name-based ID filter applied (if any)"
    )


class HubFiltersResponse(BaseModel):
    """Response model for filtered hubs API"""

    status: str = "success"
    message: str = "Hubs retrieved successfully"
    data: dict = Field(
        ..., description="Response data containing hubs, pagination, and filters"
    )


# ============================================================================
# JOIN PAID MODELS
# ============================================================================


class JoinPaidRequest(BaseModel):
    """Request model for joining a club with paid subscription"""

    email: str = Field(..., description="Member's email address")
    payment_method_id: str = Field(..., description="Stripe payment method ID")
    price: float = Field(..., gt=0, description="Price to be paid")
    price_id: str = Field(..., description="Stripe price ID for validation")
    club_name_based_id: str = Field(
        ..., description="Name-based ID of the club to join"
    )
    pricing_plan: PricingPlan = Field(
        ..., description="Pricing plan (monthly, quarterly, yearly)"
    )


class PaidMemberDetails(BaseModel):
    """Model for paid member details stored in clubs collection"""

    user_id: str = Field(description="Member's user ID")
    full_name: str = Field(description="Member's full name")
    email: str = Field(description="Member's email")
    status: str = Field(description="Member status (active, inactive)")
    membership_type: str = Field(description="Membership type (paid)")
    membership_status: str = Field(description="Membership status (active, expired)")
    join_date: datetime = Field(description="When the member joined")
    end_date: datetime = Field(description="When the membership expires")
    pricing_plan: PricingPlan = Field(
        description="Pricing plan (monthly, quarterly, yearly)"
    )
    amount_paid: float = Field(description="Amount paid for this membership")
    payment_id: str = Field(description="Stripe payment intent ID")


class JoinPaidResponse(BaseModel):
    """Response model for joining a club with paid subscription"""

    success: bool = Field(description="Whether the join operation was successful")
    message: str = Field(description="Success or error message")
    club_id: Optional[str] = Field(None, description="ID of the club joined")
    club_name: Optional[str] = Field(None, description="Name of the club joined")
    club_name_based_id: Optional[str] = Field(
        None, description="Name-based ID of the club joined"
    )
    captain_name: Optional[str] = Field(None, description="Name of the club captain")
    member_details: Optional[PaidMemberDetails] = Field(
        None, description="Member details"
    )
    join_date: Optional[datetime] = Field(None, description="When the member joined")
    end_date: Optional[datetime] = Field(
        None, description="When the membership expires"
    )
    pricing_plan: Optional[PricingPlan] = Field(
        None, description="Pricing plan selected"
    )
    amount_paid: Optional[float] = Field(None, description="Amount paid")
    payment_id: Optional[str] = Field(None, description="Stripe payment intent ID")
    member_count: Optional[int] = Field(
        None, description="Total member count in the club"
    )
    paid_member_count: Optional[int] = Field(
        None, description="Paid member count in the club"
    )
    total_clubs_joined: Optional[int] = Field(
        None, description="Total clubs joined by member (free + paid)"
    )
    paid_clubs_joined: Optional[int] = Field(
        None, description="Paid clubs joined by member"
    )


# ============================================================================
# MODERATOR VIEW API MODELS
# ============================================================================


class ModeratorViewRequest(BaseModel):
    """Request model for viewing club moderators"""

    club_id: str = Field(
        ..., description="Club ID or name_based_id to view moderators for"
    )
    page: int = Field(default=1, ge=1, description="Page number for pagination")
    page_size: int = Field(
        default=10, ge=1, le=100, description="Number of moderators per page"
    )


class ModeratorViewResponse(BaseModel):
    """Response model for moderator view API"""

    success: bool = Field(description="Whether the request was successful")
    message: str = Field(description="Success or error message")
    club_id: str = Field(description="Club ID")
    club_name: str = Field(description="Club name")
    club_name_based_id: str = Field(description="Club name-based ID")
    moderators: List[DetailedModeratorInfo] = Field(
        description="List of detailed moderator information"
    )
    pagination: dict = Field(description="Pagination information")
    moderator_stats: dict = Field(description="Moderator statistics")


# ============================================================================
# MEMBER VIEW API MODELS
# ============================================================================


class MemberViewRequest(BaseModel):
    """Request model for viewing club members"""

    club_id: str = Field(
        ..., description="Club ID or name_based_id to view members for"
    )
    page: int = Field(default=1, ge=1, description="Page number for pagination")
    page_size: int = Field(
        default=10, ge=1, le=100, description="Number of members per page"
    )


class DetailedMemberInfo(BaseModel):
    """Model for detailed member information"""

    user_id: str = Field(description="Member's user ID")
    full_name: str = Field(description="Member's full name")
    email: str = Field(description="Member's email address")
    phone: Optional[str] = Field(None, description="Member's phone number")
    avatar_url: Optional[str] = Field(None, description="Member's avatar URL")
    membership_type: str = Field(description="Membership type (trial, paid)")
    membership_status: str = Field(
        description="Membership status (active, inactive, expired)"
    )
    pricing_plan: str = Field(
        description="Pricing plan (trial, monthly, quarterly, yearly)"
    )
    join_date: datetime = Field(description="When the member joined the club")
    end_date: datetime = Field(description="When the membership expires")
    is_trial: bool = Field(description="Whether this is a trial membership")
    is_active: bool = Field(description="Whether the member is currently active")
    is_temporarily_deleted: bool = Field(False, description="Whether the member is temporarily deleted")
    last_seen: datetime = Field(description="When the member was last seen")
    payment_id: Optional[str] = Field(None, description="Payment ID if paid membership")
    amount_paid: float = Field(description="Amount paid for membership")
    created_at: datetime = Field(description="When the membership was created")
    updated_at: datetime = Field(description="When the membership was last updated")


class MemberViewResponse(BaseModel):
    """Response model for member view API"""

    success: bool = Field(description="Whether the request was successful")
    message: str = Field(description="Success or error message")
    club_id: str = Field(description="Club ID")
    club_name: str = Field(description="Club name")
    club_name_based_id: str = Field(description="Club name-based ID")
    members: List[DetailedMemberInfo] = Field(
        description="List of detailed member information"
    )
    pagination: dict = Field(description="Pagination information")
    member_stats: dict = Field(description="Member statistics")


# ============================================================================
# MEMBER PRICING API MODELS
# ============================================================================


class MemberPricingRequest(BaseModel):
    """Request model for member pricing details"""

    club_id: str = Field(..., description="Club ID or name_based_id to get pricing for")
    frequency: str = Field(
        ...,
        description="Pricing frequency (daily, weekly, monthly, quarterly, yearly, lifetime)",
    )


class PricingPlanDetails(BaseModel):
    """Model for pricing plan details"""

    frequency: str = Field(
        description="Pricing frequency (daily, weekly, monthly, quarterly, yearly, lifetime)"
    )
    price: float = Field(description="Price for this frequency")
    currency: str = Field(description="Currency code (USD, EUR, etc.)")
    stripe_product_id: str = Field(description="Stripe product ID")
    stripe_price_id: str = Field(description="Stripe price ID")
    created_at: datetime = Field(description="When the pricing plan was created")
    updated_at: datetime = Field(description="When the pricing plan was last updated")


class MemberPricingResponse(BaseModel):
    """Response model for member pricing API"""

    success: bool = Field(description="Whether the request was successful")
    message: str = Field(description="Success or error message")
    club_id: str = Field(description="Club ID")
    logo_url: Optional[str] = Field(None, description="URL to club logo/image")
    club_name: str = Field(description="Club name")
    club_name_based_id: str = Field(description="Club name-based ID")
    member_type: str = Field(description="Member type (trial, paid)")
    current_frequency: str = Field(description="Current membership frequency")
    pricing_plan: Optional[PricingPlanDetails] = Field(
        None, description="Pricing plan details for requested frequency"
    )
    all_pricing_plans: List[PricingPlanDetails] = Field(
        description="All available pricing plans for the club"
    )
    member_join_date: Optional[datetime] = Field(
        None, description="When the member joined the club"
    )
    member_end_date: Optional[datetime] = Field(
        None, description="When the membership expires"
    )


class PricingPlanEdit(BaseModel):
    """Model for editing existing pricing plans"""

    frequency: str = Field(description="Pricing frequency (monthly, quarterly, yearly)")
    price: float = Field(..., gt=0, description="Price must be greater than 0")
    currency: str = Field(default="USD", description="Currency code")
    stripe_price_id: Optional[str] = Field(
        None, description="Existing Stripe price ID (for updates)"
    )


class PricingPlanCreate(BaseModel):
    """Model for creating new pricing plans"""

    frequency: str = Field(description="Pricing frequency (monthly, quarterly, yearly)")
    price: float = Field(..., gt=0, description="Price must be greater than 0")
    currency: str = Field(default="USD", description="Currency code")


class ClubEditRequest(BaseModel):
    """Request model for editing club details"""

    club_id: str = Field(..., description="Club ID to edit")
    name: Optional[str] = Field(
        None, min_length=3, max_length=100, description="Updated club name"
    )
    description: Optional[str] = Field(
        None, min_length=10, max_length=500, description="Updated club description"
    )
    sub_description: Optional[str] = Field(
        None, min_length=5, max_length=200, description="Updated sub description"
    )
    logo_url: Optional[str] = Field(None, description="Updated logo URL")
    whats_included: Optional[List[WhatsIncludedItem]] = Field(
        None, description="Updated what's included list"
    )
    top_3_sports: Optional[List[SportInfo]] = Field(
        None, description="Updated top 3 sports list"
    )
    pricing_plans_edit: Optional[List[PricingPlanEdit]] = Field(
        None, description="Existing pricing plans to update"
    )
    pricing_plans_add: Optional[List[PricingPlanCreate]] = Field(
        None, description="New pricing plans to add"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Club name cannot be empty")
        return v.strip() if v else v


class ClubEditResponse(BaseModel):
    """Response model for club editing"""

    success: bool = Field(description="Whether the edit was successful")
    message: str = Field(description="Success or error message")
    club_id: str = Field(description="Club ID that was edited")
    club_name: str = Field(description="Updated club name")
    updated_fields: List[str] = Field(description="List of fields that were updated")
    pricing_plans_updated: int = Field(description="Number of pricing plans updated")
    pricing_plans_added: int = Field(description="Number of new pricing plans added")
    members_notified: int = Field(
        description="Number of members notified about changes"
    )


class SimpleClubResponse(BaseModel):
    """Simple club response model with only essential fields"""
    
    id: str = Field(description="Club ObjectId")
    name: str = Field(description="Club name")
    name_based_id: str = Field(description="Club name-based ID")


class SimpleClubListResponse(BaseModel):
    """Response model for simple club list with pagination"""
    
    clubs: List[SimpleClubResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


class SoftDeleteMemberRequest(BaseModel):
    """Request model for soft deleting a member"""

    club_id: str = Field(..., description="Club ID where the member is to be deleted")
    member_user_id: str = Field(
        ..., description="User ID of the member to be soft deleted"
    )

    @field_validator("club_id")
    @classmethod
    def validate_club_id(cls, v):
        if not v or not v.strip():
            raise ValueError("Club ID cannot be empty")
        return v.strip()

    @field_validator("member_user_id")
    @classmethod
    def validate_member_user_id(cls, v):
        if not v or not v.strip():
            raise ValueError("Member user ID cannot be empty")
        return v.strip()


class SoftDeleteMemberResponse(BaseModel):
    """Response model for soft deleting a member"""

    success: bool = Field(description="Whether the soft delete was successful")
    message: str = Field(description="Success or error message")
    club_id: str = Field(description="Club ID where member was deleted")
    club_name: str = Field(description="Name of the club")
    member_user_id: str = Field(description="User ID of the deleted member")
    member_name: str = Field(description="Name of the deleted member")
    membership_type: str = Field(description="Type of membership (trial/paid)")
    updated_arrays: List[str] = Field(
        description="Arrays that were updated (paid_members/members)"
    )


# ============================================================================
# ADD MODERATORS TO EXISTING CLUB API MODELS
# ============================================================================


class AddModeratorsRequest(BaseModel):
    """Request model for adding moderators to existing club"""

    club_name_based_id: str = Field(..., description="Club name-based ID")
    captain_email: str = Field(..., description="Captain's email for verification")
    moderator_emails: List[str] = Field(
        ..., min_items=1, description="List of moderator emails to add"
    )
    payment_method_id: Optional[str] = Field(
        None, description="Stripe payment method ID for payment"
    )

    @field_validator("club_name_based_id")
    @classmethod
    def validate_club_id(cls, v):
        if not v or not v.strip():
            raise ValueError("Club name-based ID cannot be empty")
        return v.strip()

    @field_validator("captain_email")
    @classmethod
    def validate_captain_email(cls, v):
        if not v or not v.strip():
            raise ValueError("Captain email cannot be empty")
        if "@" not in v:
            raise ValueError("Invalid email format")
        return v.strip().lower()

    @field_validator("moderator_emails")
    @classmethod
    def validate_moderator_emails(cls, v):
        if not v:
            raise ValueError("At least one moderator email is required")

        # Check for duplicates
        if len(v) != len(set(v)):
            raise ValueError("Duplicate moderator emails are not allowed")

        # Validate email format
        for email in v:
            if not email or not email.strip():
                raise ValueError("Moderator email cannot be empty")
            if "@" not in email:
                raise ValueError(f"Invalid email format: {email}")

        return [email.strip().lower() for email in v]


class AddModeratorsResponse(BaseModel):
    """Response model for adding moderators to existing club"""

    success: bool = Field(description="Whether the request was successful")
    message: str = Field(description="Success or error message")
    club_id: str = Field(description="Club ID")
    club_name: str = Field(description="Club name")
    club_name_based_id: str = Field(description="Club name-based ID")
    captain_email: str = Field(description="Captain's email")
    moderators_added: int = Field(description="Number of moderators successfully added")
    moderators_skipped: int = Field(
        description="Number of moderators skipped (already exist)"
    )
    total_moderators: int = Field(description="Total moderators in club after addition")
    payment_intent_id: Optional[str] = Field(
        None, description="Stripe payment intent ID"
    )
    payment_status: Optional[str] = Field(None, description="Payment status")
    total_amount_paid: float = Field(description="Total amount paid for moderators")
    moderator_details: List[DetailedModeratorInfo] = Field(
        description="Details of added moderators"
    )
    added_at: datetime = Field(description="When moderators were added")


# ========================================
# Moderator Management API Models
# ========================================

class ModeratorDeleteRequest(BaseModel):
    """Request model for deleting a moderator"""
    
    club_name_based_id: str = Field(..., description="Club's name_based_id (e.g., 'new-test')")
    moderator_user_id: str = Field(..., description="User ID of the moderator to delete")
    reason: Optional[str] = Field(None, description="Reason for deletion")
    notify_moderator: bool = Field(default=True, description="Whether to notify the moderator")


class ModeratorReactivateRequest(BaseModel):
    """Request model for reactivating a moderator"""
    
    club_name_based_id: str = Field(..., description="Club's name_based_id (e.g., 'new-test')")
    moderator_user_id: str = Field(..., description="User ID of the moderator to reactivate")
    notify_moderator: bool = Field(default=True, description="Whether to notify the moderator")


class ModeratorInfo(BaseModel):
    """Moderator information in response"""
    
    user_id: str = Field(..., description="Moderator's user ID")
    full_name: str = Field(..., description="Moderator's full name")
    email: str = Field(..., description="Moderator's email")
    type_of_moderator: str = Field(..., description="Type: 'free' or 'paid'")
    status: str = Field(..., description="Current status: 'active' or 'inactive'")
    deleted_at: Optional[datetime] = Field(None, description="Deletion timestamp")
    deleted_by: Optional[str] = Field(None, description="Captain who deleted the moderator")
    reactivated_at: Optional[datetime] = Field(None, description="Reactivation timestamp")
    reactivated_by: Optional[str] = Field(None, description="Captain who reactivated the moderator")


class ModeratorCounts(BaseModel):
    """Updated moderator counts after operation"""
    
    total_moderators: int = Field(..., description="Total active moderators")
    free_moderators: int = Field(..., description="Number of free moderators")
    paid_moderators: int = Field(..., description="Number of paid moderators")


class ModeratorDeleteResponse(BaseModel):
    """Response model for moderator deletion"""
    
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Response message")
    club_id: str = Field(..., description="Club's ObjectId")
    club_name: str = Field(..., description="Club name")
    club_name_based_id: str = Field(..., description="Club's name_based_id")
    moderator_info: ModeratorInfo = Field(..., description="Deleted moderator information")
    updated_counts: ModeratorCounts = Field(..., description="Updated moderator counts")
    deleted_at: str = Field(..., description="Deletion timestamp (ISO format)")


class ModeratorReactivateResponse(BaseModel):
    """Response model for moderator reactivation"""
    
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Response message")
    club_id: str = Field(..., description="Club's ObjectId")
    club_name: str = Field(..., description="Club name")
    club_name_based_id: str = Field(..., description="Club's name_based_id")
    moderator_info: ModeratorInfo = Field(..., description="Reactivated moderator information")
    updated_counts: ModeratorCounts = Field(..., description="Updated moderator counts")
    reactivated_at: str = Field(..., description="Reactivation timestamp (ISO format)")


# ========================================
# Moderator Details API Models
# ========================================

class ModeratorDetailsRequest(BaseModel):
    """Request model for getting moderator details"""
    
    club_name_based_id: str = Field(..., description="Club's name_based_id (e.g., 'new-club')")
    moderator_user_id: str = Field(..., description="User ID of the moderator")


class ClubAssignmentInfo(BaseModel):
    """Information about a club where moderator is assigned"""
    
    club_id: str = Field(..., description="Club's ObjectId")
    club_name: str = Field(..., description="Club name")
    club_name_based_id: str = Field(..., description="Club's name_based_id")
    logo_url: Optional[str] = Field(None, description="Club logo URL")
    banner_url: Optional[str] = Field(None, description="Club banner URL")
    moderator_status: str = Field(..., description="Moderator status in this club")
    moderator_type: str = Field(..., description="Type of moderator (free/paid)")
    joined_date: Optional[datetime] = Field(None, description="When moderator joined this club")
    invited_at: Optional[datetime] = Field(None, description="When moderator was invited")


class ModeratorDetailsInfo(BaseModel):
    """Detailed moderator information"""
    
    user_id: str = Field(..., description="Moderator's user ID")
    full_name: str = Field(..., description="Moderator's full name")
    email: str = Field(..., description="Moderator's email")
    avatar_url: Optional[str] = Field(None, description="Moderator's avatar URL")
    bio: Optional[str] = Field(None, description="Moderator's bio")
    phone_number: Optional[str] = Field(None, description="Moderator's phone number")
    created_at: Optional[datetime] = Field(None, description="When moderator account was created")
    last_login: Optional[datetime] = Field(None, description="Last login timestamp")


class ModeratorDetailsResponse(BaseModel):
    """Response model for moderator details"""
    
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Response message")
    moderator_details: ModeratorDetailsInfo = Field(..., description="Moderator's basic information")
    current_club_info: ClubAssignmentInfo = Field(..., description="Current club assignment details")
    all_club_assignments: List[ClubAssignmentInfo] = Field(..., description="All clubs where moderator is assigned")
    total_club_assignments: int = Field(..., description="Total number of club assignments")
    captain_clubs_count: int = Field(..., description="Total clubs created by the captain")


# ========================================
# CLUB PICKS/BETS MODELS
# ========================================

class PickType(str, Enum):
    """Enum for pick types - accepts case-insensitive values"""
    MONEYLINE = "Moneyline"
    PARLAY = "Parlay"
    PROP = "Prop"
    OVER_UNDER = "Over/under"
    SPREAD = "Spread"
    TEASER = "Teaser"
    FUTURES = "Futures"
    LIVE_BET = "Live Bet"
    ROUND_ROBIN = "Round Robin"
    IF_BET = "If Bet"
    REVERSE = "Reverse"
    STRAIGHT_BET = "Straight Bet"
    TOTAL = "Total"
    ALTERNATIVE_SPREAD = "Alternative Spread"
    ALTERNATIVE_TOTAL = "Alternative Total"
    SAME_GAME_PARLAY = "Same Game Parlay"
    OTHER = "Other"
    
    @classmethod
    def _missing_(cls, value):
        """Handle case-insensitive enum matching"""
        if isinstance(value, str):
            # Normalize the value for comparison
            value_normalized = value.strip()
            for member in cls:
                # Case-insensitive comparison
                if member.value.lower() == value_normalized.lower():
                    return member
        return None


class PickEntityType(str, Enum):
    """Enum for pick entity type (team or player)"""
    TEAM = "team"
    PLAYER = "player"


class PickStatus(str, Enum):
    """Enum for pick status - accepts case-insensitive values, stores as lowercase"""
    PENDING = "pending"
    COMPLETED = "completed"
    
    @classmethod
    def _missing_(cls, value):
        """Handle case-insensitive enum matching"""
        if isinstance(value, str):
            value_lower = value.lower()
            for member in cls:
                if member.value == value_lower:
                    return member
        return None

class BetSource(str, Enum):
    LIVE_SUPPORT = "live-support"
    MANUAL_ENTRY = "manual-entry"
    @classmethod
    def _missing_(cls, value):
        """Handle case-insensitive enum matching"""
        if isinstance(value, str):
            value_lower = value.lower()
            for member in cls:
                if member.value == value_lower:
                    return member
        return None


class PickResult(str, Enum):
    """Enum for pick result - accepts case-insensitive values, stores as lowercase"""
    WIN = "win"
    LOSS = "loss"
    
    @classmethod
    def _missing_(cls, value):
        """Handle case-insensitive enum matching"""
        if isinstance(value, str):
            value_lower = value.lower()
            for member in cls:
                if member.value == value_lower:
                    return member
        return None


class BetSource(str, Enum):
    """Enum for bet source - live-support or manual-entry"""
    LIVE_SUPPORT = "live-support"
    MANUAL_ENTRY = "manual-entry"
    
    @classmethod
    def _missing_(cls, value):
        """Handle case-insensitive enum matching"""
        if isinstance(value, str):
            value_lower = value.lower().replace(" ", "-")
            for member in cls:
                if member.value == value_lower:
                    return member
        return None


class ParlayPick(BaseModel):
    """Model for individual parlay pick within a parlay bet"""
    market_type: str = Field(..., min_length=2, max_length=50, description="Market type for this parlay pick (e.g., 'Moneyline', 'Over/Under')")
    sport: str = Field(..., min_length=2, max_length=50, description="Sport name for this parlay pick")
    league: str = Field(..., min_length=2, max_length=50, description="League name for this parlay pick")
    pick_entity_type: PickEntityType = Field(..., description="Whether this parlay pick is for team or player")
    
    # Team fields (required if pick_entity_type is 'team')
    team1: Optional[str] = Field(None, min_length=2, max_length=100, description="First team name (required if pick_entity_type is 'team')")
    team2: Optional[str] = Field(None, min_length=2, max_length=100, description="Second team name (required if pick_entity_type is 'team')")
    
    # Player field (required if pick_entity_type is 'player')
    player_name: Optional[str] = Field(None, min_length=2, max_length=100, description="Player name (required if pick_entity_type is 'player')")
    
    # ID fields for sports API integration
    player_id: Optional[str] = Field(None, description="Player ID from sports API")
    home_team_id: Optional[str] = Field(None, description="Home team ID from sports API")
    away_team_id: Optional[str] = Field(None, description="Away team ID from sports API")
    bet_on_team_id: Optional[str] = Field(None, description="Team ID that the bet is on from sports API")
    league_id: Optional[str] = Field(None, description="League ID from sports API")
    match_id: Optional[str] = Field(None, description="Match ID from sports API")
    
    # Logo fields (passed as parameters, not fetched from sports API)
    home_logo: Optional[str] = Field(None, max_length=500, description="Home team logo URL")
    away_logo: Optional[str] = Field(None, max_length=500, description="Away team logo URL")
    
    bet_for: str = Field(..., min_length=1, max_length=200, description="What the bet is for (e.g., 'Manchester United', 'Over 2.5', 'Over 25.5 points')")
    match_datetime: datetime = Field(..., description="Date and time for this specific parlay pick (ISO 8601 format)")
    
    # Parlay status and result fields
    parlay_status: Optional[str] = Field(default="pending", description="Status of this parlay pick: 'pending' or 'completed' (stored as lowercase)")
    parlay_result: Optional[str] = Field(None, description="Result of this parlay pick: 'win' or 'loss' (required when parlay_status is 'completed', stored as lowercase)")
    
    @field_validator("parlay_status", mode='before')
    @classmethod
    def normalize_parlay_status(cls, v):
        """Normalize parlay_status to lowercase for case-insensitive handling"""
        if isinstance(v, str):
            return v.lower()
        return v or "pending"
    
    @field_validator("parlay_result", mode='before')
    @classmethod
    def normalize_parlay_result(cls, v, info):
        """Normalize parlay_result to lowercase and validate"""
        values = info.data
        parlay_status = values.get("parlay_status", "pending")
        
        # Normalize status if it's a string
        if isinstance(parlay_status, str):
            parlay_status = parlay_status.lower()
        
        # If parlay_status is completed, parlay_result is required
        if parlay_status == "completed":
            if not v:
                raise ValueError("parlay_result is required when parlay_status is 'completed'")
            if isinstance(v, str):
                v_lower = v.lower()
                if v_lower not in ['win', 'loss']:
                    raise ValueError("parlay_result must be either 'win' or 'loss'")
                return v_lower
        
        # Normalize result if provided
        if isinstance(v, str):
            v_lower = v.lower()
            if v_lower not in ['win', 'loss']:
                raise ValueError("parlay_result must be either 'win' or 'loss'")
            return v_lower
        
        return v
    
    @field_validator("team1", "team2")
    @classmethod
    def validate_teams(cls, v, info):
        """Validate that both teams are provided when pick_entity_type is 'team'"""
        values = info.data
        if values.get("pick_entity_type") == PickEntityType.TEAM:
            if not v:
                raise ValueError("Both team1 and team2 are required when pick_entity_type is 'team'")
        return v
    
    @field_validator("player_name")
    @classmethod
    def validate_player(cls, v, info):
        """Validate that player_name is provided when pick_entity_type is 'player'"""
        values = info.data
        if values.get("pick_entity_type") == PickEntityType.PLAYER:
            if not v:
                raise ValueError("player_name is required when pick_entity_type is 'player'")
        return v
    
    @field_validator("sport")
    @classmethod
    def validate_sport_lowercase(cls, v):
        """Normalize sport to lowercase for consistency"""
        if v:
            return v.lower().strip()
        return v


class ClubPickCreateRequest(BaseModel):
    """Request model for creating a new pick"""
    
    club_id: str = Field(..., description="Club name-based ID (e.g., 'my-club')")
    bet_source: BetSource = Field(..., description="Source of the bet: 'live-support' or 'manual-entry'")
    sport: Optional[str] = Field(None, min_length=2, max_length=50, description="Sport name (e.g., 'Basketball', 'Football') - optional when pick_type is 'Parlay'")
    league: Optional[str] = Field(None, min_length=2, max_length=50, description="League name (e.g., 'NBA', 'NFL') - optional when pick_type is 'Parlay'")
    pick_entity_type: Optional[PickEntityType] = Field(None, description="Whether pick is for team or player (optional when pick_type is 'Parlay')")
    
    # Team fields (required if pick_entity_type is 'team')
    team1: Optional[str] = Field(None, min_length=2, max_length=100, description="First team name (required if pick_entity_type is 'team')")
    team2: Optional[str] = Field(None, min_length=2, max_length=100, description="Second team name (required if pick_entity_type is 'team')")
    
    # Player field (required if pick_entity_type is 'player')
    player_name: Optional[str] = Field(None, min_length=2, max_length=100, description="Player name (required if pick_entity_type is 'player')")
    
    # bet_on_team: Optional field for all bet sources (live-support or manual-entry)
    bet_on_team: Optional[str] = Field(None, min_length=2, max_length=100, description="Which team the bet is on (optional for all bet sources)")
    
    # ID fields for sports API integration
    player_id: Optional[str] = Field(None, description="Player ID from sports API")
    home_team_id: Optional[str] = Field(None, description="Home team ID from sports API")
    away_team_id: Optional[str] = Field(None, description="Away team ID from sports API")
    bet_on_team_id: Optional[str] = Field(None, description="Team ID that the bet is on from sports API")
    league_id: Optional[str] = Field(None, description="League ID from sports API")
    match_id: Optional[str] = Field(None, description="Match ID from sports API")
    
    # Logo fields (passed as parameters, not fetched from sports API)
    home_logo: Optional[str] = Field(None, max_length=500, description="Home team logo URL")
    away_logo: Optional[str] = Field(None, max_length=500, description="Away team logo URL")
    
    match_datetime: Optional[datetime] = Field(None, description="Date and time when the match/game will happen (ISO 8601 format) - optional when pick_type is 'Parlay'")
    platform: Optional[str] = Field(None, min_length=2, max_length=50, description="Betting platform (e.g., 'DraftKings', 'FanDuel') - optional when pick_type is 'Parlay'")
    pick_type: str = Field(..., min_length=2, max_length=50, description="Type of pick - accepts any custom value (e.g., 'Over/under', 'Moneyline', 'Overlay', 'Parlay', or any custom type)")
    status: PickStatus = Field(default=PickStatus.PENDING, description="Status of the pick (accepts: Pending, pending, Completed, completed)")
    reasoning: Optional[str] = Field(None, max_length=500, description="Optional reasoning for the pick")
    result: Optional[PickResult] = Field(None, description="Result of the pick (accepts: Win, win, Loss, loss) - required if status is completed")
    bet_logo: Optional[str] = Field(None, max_length=500, description="URL of the bet logo/image")
    
    # Parlay picks: Required when pick_type is 'Parlay' (2-10 picks)
    parlay_picks: Optional[List[ParlayPick]] = Field(None, min_length=2, max_length=10, description="Array of parlay picks (required when pick_type is 'Parlay', must have 2-10 picks)")
    
    @field_validator("status", mode='before')
    @classmethod
    def normalize_status(cls, v):
        """Normalize status to lowercase for case-insensitive handling"""
        if isinstance(v, str):
            return v.lower()
        return v
    
    @field_validator("result", mode='before')
    @classmethod
    def normalize_result_before(cls, v):
        """Normalize result to lowercase for case-insensitive handling"""
        if isinstance(v, str):
            v_lower = v.lower()
            # Custom validation with better error message
            if v_lower not in ['win', 'loss']:
                raise ValueError("Result should be Win or Lost")
            return v_lower
        return v
    
    @field_validator("team1", "team2")
    @classmethod
    def validate_teams(cls, v, info):
        """Validate that both teams are provided when pick_entity_type is 'team'"""
        values = info.data
        pick_type = values.get("pick_type", "").lower()
        # Skip validation if pick_type is "Parlay"
        if pick_type == "parlay":
            return v
        if values.get("pick_entity_type") == PickEntityType.TEAM:
            if not v:
                raise ValueError("Both team1 and team2 are required when pick_entity_type is 'team'")
        return v
    
    @field_validator("player_name")
    @classmethod
    def validate_player(cls, v, info):
        """Validate that player_name is provided when pick_entity_type is 'player'"""
        values = info.data
        pick_type = values.get("pick_type", "").lower()
        # Skip validation if pick_type is "Parlay"
        if pick_type == "parlay":
            return v
        if values.get("pick_entity_type") == PickEntityType.PLAYER:
            if not v:
                raise ValueError("player_name is required when pick_entity_type is 'player'")
        return v
    
    @field_validator("result")
    @classmethod
    def validate_result(cls, v, info):
        """Validate that result is provided when status is completed"""
        values = info.data
        if values.get("status") == PickStatus.COMPLETED and not v:
            raise ValueError("Result is required when status is 'completed'")
        if values.get("status") == PickStatus.PENDING and v:
            raise ValueError("Result should not be provided when status is 'pending'")
        return v
    
    @field_validator("sport")
    @classmethod
    def validate_sport(cls, v, info):
        """Validate sport restrictions for live-support bets and normalize to lowercase"""
        values = info.data
        pick_type = values.get("pick_type", "").lower()
        
        # Skip validation if pick_type is "Parlay" and sport is None
        if pick_type == "parlay" and v is None:
            return v
        
        # If sport is None and not Parlay, it's required
        if v is None:
            raise ValueError("sport is required when pick_type is not 'Parlay'")
        
        bet_source = values.get("bet_source")
        pick_entity_type = values.get("pick_entity_type")
        
        # Normalize sport to lowercase
        sport_lower = v.lower().strip()
        
        # If live-support and NOT parlay (for both team and player picks), only allow Basketball or American Football
        if (bet_source and hasattr(bet_source, 'value') and bet_source.value == "live-support" and
            pick_type != "parlay"):
            allowed_sports = ["basketball", "american football"]
            if sport_lower not in allowed_sports:
                entity_type_str = "team" if pick_entity_type == PickEntityType.TEAM else "player"
                raise ValueError(f"For live-support {entity_type_str} picks (non-parlay), only 'Basketball' or 'American Football' are allowed")
        
        # Return lowercase sport for consistency
        return sport_lower
    
    @field_validator("league")
    @classmethod
    def validate_league(cls, v, info):
        """Validate league field - optional when pick_type is 'Parlay'"""
        values = info.data
        pick_type = values.get("pick_type", "").lower()
        
        # Skip validation if pick_type is "Parlay" and league is None
        if pick_type == "parlay" and v is None:
            return v
        
        # If league is None and not Parlay, it's required
        if v is None:
            raise ValueError("league is required when pick_type is not 'Parlay'")
        
        return v
    
    @field_validator("match_datetime")
    @classmethod
    def validate_match_datetime(cls, v, info):
        """Validate match_datetime field - optional when pick_type is 'Parlay'"""
        values = info.data
        pick_type = values.get("pick_type", "").lower()
        
        # Skip validation if pick_type is "Parlay" and match_datetime is None
        if pick_type == "parlay" and v is None:
            return v
        
        # If match_datetime is None and not Parlay, it's required
        if v is None:
            raise ValueError("match_datetime is required when pick_type is not 'Parlay'")
        
        return v
    
    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v, info):
        """Validate platform field - optional when pick_type is 'Parlay'"""
        values = info.data
        pick_type = values.get("pick_type", "").lower()
        
        # Skip validation if pick_type is "Parlay" and platform is None
        if pick_type == "parlay" and v is None:
            return v
        
        # If platform is None and not Parlay, it's required
        if v is None:
            raise ValueError("platform is required when pick_type is not 'Parlay'")
        
        return v
    
    @field_validator("bet_on_team")
    @classmethod
    def validate_bet_on_team(cls, v, info):
        """Validate bet_on_team field rules"""
        values = info.data
        pick_type = values.get("pick_type", "").lower()
        bet_source = values.get("bet_source")
        pick_entity_type = values.get("pick_entity_type")
        
        # Skip validation if pick_type is "Parlay"
        if pick_type == "parlay":
            return v
        
        # bet_on_team is optional for all bet sources (live-support and manual-entry)
        # No validation required - field is optional
        return v
    
    @field_validator("parlay_picks")
    @classmethod
    def validate_parlay_picks(cls, v, info):
        """Validate parlay_picks field"""
        values = info.data
        pick_type = values.get("pick_type", "").lower()
        
        # If pick_type is "Parlay", parlay_picks is required and must have 2-10 picks
        if pick_type == "parlay":
            if not v:
                raise ValueError("parlay_picks is required when pick_type is 'Parlay'")
            if len(v) < 2:
                raise ValueError("parlay_picks must have at least 2 picks when pick_type is 'Parlay'")
            if len(v) > 10:
                raise ValueError("parlay_picks can have at most 10 picks when pick_type is 'Parlay'")
        
        # If pick_type is NOT "Parlay", parlay_picks should not be provided
        if pick_type != "parlay" and v:
            raise ValueError("parlay_picks should only be provided when pick_type is 'Parlay'")
        
        return v


class ClubPickUpdateRequest(BaseModel):
    """Request model for updating a pick"""
    
    sport: Optional[str] = Field(None, min_length=2, max_length=50, description="Sport name")
    league: Optional[str] = Field(None, min_length=2, max_length=50, description="League name")
    pick_entity_type: Optional[PickEntityType] = Field(None, description="Whether pick is for team or player")
    team1: Optional[str] = Field(None, min_length=2, max_length=100, description="First team name")
    team2: Optional[str] = Field(None, min_length=2, max_length=100, description="Second team name")
    player_name: Optional[str] = Field(None, min_length=2, max_length=100, description="Player name")
    bet_on_team: Optional[str] = Field(None, min_length=2, max_length=100, description="Which team the bet is on")
    player_id: Optional[str] = Field(None, description="Player ID from sports API")
    home_team_id: Optional[str] = Field(None, description="Home team ID from sports API")
    away_team_id: Optional[str] = Field(None, description="Away team ID from sports API")
    bet_on_team_id: Optional[str] = Field(None, description="Team ID that the bet is on from sports API")
    league_id: Optional[str] = Field(None, description="League ID from sports API")
    match_id: Optional[str] = Field(None, description="Match ID from sports API")
    match_datetime: Optional[datetime] = Field(None, description="Date and time when the match/game will happen")
    platform: Optional[str] = Field(None, min_length=2, max_length=50, description="Betting platform")
    pick_type: Optional[str] = Field(None, min_length=2, max_length=50, description="Type of pick - accepts any custom value (e.g., 'Over/under', 'Moneyline', 'Overlay', or any custom type)")
    status: Optional[PickStatus] = Field(None, description="Status of the pick (accepts: Pending, pending, Completed, completed)")
    reasoning: Optional[str] = Field(None, max_length=500, description="Reasoning for the pick")
    result: Optional[PickResult] = Field(None, description="Result of the pick (accepts: Win, win, Loss, loss)")
    bet_logo: Optional[str] = Field(None, max_length=500, description="URL of the bet logo/image")
    parlay_picks: Optional[List[Dict[str, Any]]] = Field(None, description="Array of parlay picks (for updating parlay picks). Can be partial update with only parlay_status/parlay_result, or full update with all fields")
    
    @field_validator("status", mode='before')
    @classmethod
    def normalize_status(cls, v):
        """Normalize status to lowercase for case-insensitive handling"""
        if isinstance(v, str):
            return v.lower()
        return v
    
    @field_validator("result", mode='before')
    @classmethod
    def normalize_result_before(cls, v):
        """Normalize result to lowercase for case-insensitive handling"""
        if isinstance(v, str):
            v_lower = v.lower()
            # Custom validation with better error message
            if v_lower not in ['win', 'loss']:
                raise ValueError("Result should be Win or Lost")
            return v_lower
        return v
    
    @field_validator("result")
    @classmethod
    def validate_result(cls, v, info):
        """Validate that result is provided when status is completed"""
        values = info.data
        if values.get("status") == PickStatus.COMPLETED and not v:
            raise ValueError("Result is required when status is 'completed'")
        return v


class ClubPickResponse(BaseModel):
    """Response model for a club pick"""
    
    id: str = Field(..., description="Pick ID")
    club_id: str = Field(..., description="Club name-based ID")
    club_name: Optional[str] = Field(None, description="Club name")
    submitted_by: str = Field(..., description="User ID who submitted the pick")
    submitted_by_role: str = Field(..., description="Role of submitter (captain/moderator)")
    sport: str = Field(..., description="Sport name")
    league: str = Field(..., description="League name")
    pick_entity_type: str = Field(..., description="Whether pick is for team or player")
    team1: Optional[str] = Field(None, description="First team name")
    team2: Optional[str] = Field(None, description="Second team name")
    player_name: Optional[str] = Field(None, description="Player name")
    match_datetime: datetime = Field(..., description="When the match/game will happen")
    platform: str = Field(..., description="Betting platform")
    pick_type: str = Field(..., description="Type of pick")
    status: str = Field(..., description="Status of the pick")
    reasoning: Optional[str] = Field(None, description="Reasoning for the pick")
    result: Optional[str] = Field(None, description="Result of the pick")
    bet_logo: Optional[str] = Field(None, description="URL of the bet logo/image")
    created_at: datetime = Field(..., description="When the pick was created")
    updated_at: datetime = Field(..., description="When the pick was last updated")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ClubPickListResponse(BaseModel):
    """Response model for list of club picks"""
    
    picks: List[ClubPickResponse] = Field(..., description="List of picks")
    total: int = Field(..., description="Total number of picks")
    limit: int = Field(..., description="Limit per page")
    skip: int = Field(..., description="Number of picks skipped")
    page: int = Field(..., description="Current page number")
    total_pages: int = Field(..., description="Total number of pages")


class ClubPickStatsResponse(BaseModel):
    """Response model for club pick statistics"""
    
    club_id: str = Field(..., description="Club name-based ID")
    total_picks: int = Field(..., description="Total number of picks")
    pending_picks: int = Field(..., description="Number of pending picks")
    completed_picks: int = Field(..., description="Number of completed picks")
    wins: int = Field(..., description="Number of wins")
    losses: int = Field(..., description="Number of losses")
    win_percentage: float = Field(..., description="Win percentage")


class LeaderboardEntry(BaseModel):
    """Individual entry in the club leaderboard"""
    
    rank: int = Field(..., description="Rank position (1 = best)")
    user_id: str = Field(..., description="User ID")
    full_name: str = Field(..., description="Full name of the captain/moderator")
    user_role: str = Field(..., description="Role in club (captain/moderator)")
    total_picks: int = Field(..., description="Total number of picks submitted")
    wins: int = Field(..., description="Number of wins")
    losses: int = Field(..., description="Number of losses")
    pending: int = Field(..., description="Number of pending picks")
    win_percentage: float = Field(..., description="Win percentage")
    avatar_url: Optional[str] = Field(None, description="User avatar URL")


class ClubLeaderboardResponse(BaseModel):
    """Response model for club leaderboard"""
    
    club_id: str = Field(..., description="Club name-based ID")
    club_name: str = Field(..., description="Club name")
    total_participants: int = Field(..., description="Total number of captains and moderators")
    leaderboard: List[LeaderboardEntry] = Field(..., description="Leaderboard entries sorted by performance")


class GlobalLeaderboardEntry(BaseModel):
    """Individual entry in the global leaderboard"""
    
    rank: int = Field(..., description="Global rank position (1 = best)")
    user_id: str = Field(..., description="User ID")
    full_name: str = Field(..., description="Full name of the captain/moderator")
    user_role: str = Field(..., description="Role (captain/moderator)")
    club_id: str = Field(..., description="Club name-based ID")
    club_name: str = Field(..., description="Club name")
    total_picks: int = Field(..., description="Total number of picks submitted")
    wins: int = Field(..., description="Number of wins")
    losses: int = Field(..., description="Number of losses")
    win_percentage: float = Field(..., description="Win percentage")
    avatar_url: Optional[str] = Field(None, description="User avatar URL")


class GlobalLeaderboardResponse(BaseModel):
    """Response model for global leaderboard"""
    
    total_participants: int = Field(..., description="Total number of captains and moderators across all clubs")
    page: int = Field(..., description="Current page number")
    limit: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")
    leaderboard: List[GlobalLeaderboardEntry] = Field(..., description="Global leaderboard entries")


class ClubwiseLeaderboardEntry(BaseModel):
    """Individual club entry in clubwise leaderboard"""
    
    rank: int = Field(..., description="Rank position")
    club_id: str = Field(..., description="Club name-based ID")
    club_name: str = Field(..., description="Club name")
    club_logo_url: Optional[str] = Field(None, description="Club logo URL")
    user_id: str = Field(..., description="User ID of captain/moderator")
    full_name: str = Field(..., description="Name of captain/moderator")
    user_role: str = Field(..., description="Role in club")
    total_picks: int = Field(..., description="Total picks submitted")
    wins: int = Field(..., description="Number of wins")
    losses: int = Field(..., description="Number of losses")
    win_percentage: float = Field(..., description="Win percentage")


class ClubwiseLeaderboardResponse(BaseModel):
    """Response model for clubwise leaderboard"""
    
    user_id: str = Field(..., description="User ID requesting the leaderboard")
    total_clubs: int = Field(..., description="Total number of clubs user is part of")
    total_participants: int = Field(..., description="Total number of participants from user's clubs")
    page: int = Field(..., description="Current page number")
    limit: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")
    leaderboard: List[ClubwiseLeaderboardEntry] = Field(..., description="Clubwise leaderboard entries")


# ============================================================================
# CAPTAIN REVENUE MODELS
# ============================================================================

class RevenueBreakdown(BaseModel):
    """Revenue breakdown model"""
    
    captain_percentage: float = Field(..., description="Captain's percentage of revenue")
    platform_percentage: float = Field(..., description="Platform's percentage of revenue")
    captain_amount: float = Field(..., description="Captain's amount in dollars")
    platform_amount: float = Field(..., description="Platform's amount in dollars")


class ClubStatusBreakdown(BaseModel):
    """Club status breakdown model"""
    
    approved: int = Field(..., description="Number of approved clubs")
    pending: int = Field(..., description="Number of pending clubs")
    rejected: int = Field(..., description="Number of rejected clubs")
    total: int = Field(..., description="Total number of clubs")


class MemberBreakdown(BaseModel):
    """Member breakdown model"""
    
    active_members: int = Field(..., description="Total active members")
    paid_members: int = Field(..., description="Number of paid members")
    trial_members: int = Field(..., description="Number of trial members")


class ContentBreakdown(BaseModel):
    """Content breakdown model"""
    
    strategy_videos: int = Field(..., description="Number of strategy videos")
    training_videos: int = Field(..., description="Number of training videos")
    partner_links: int = Field(..., description="Number of partner links")
    total: int = Field(..., description="Total content created")


class CaptainRevenueResponse(BaseModel):
    """Response model for comprehensive captain revenue statistics"""
    
    captain_id: str = Field(..., description="Captain's user ID")
    generated_at: str = Field(..., description="Timestamp when data was generated")
    
    # Revenue metrics
    total_revenue_earned: float = Field(..., description="Total revenue earned by captain (95%)")
    # platform_fees: float = Field(..., description="Total platform fees (5%)")
    # total_revenue_generated: float = Field(..., description="Total revenue generated across all clubs")
    # available_balance: Optional[float] = Field(None, description="Available balance in Stripe Connect account")
    # revenue_breakdown: RevenueBreakdown = Field(..., description="Revenue breakdown details")
    
    # Club metrics
    total_approved_clubs: int = Field(..., description="Total number of approved clubs")
    total_clubs_created: int = Field(..., description="Total number of clubs created")
    # club_status_breakdown: ClubStatusBreakdown = Field(..., description="Club status breakdown")
    
    # Member metrics
    total_active_members: int = Field(..., description="Total active members across all clubs")
    average_revenue_per_member: float = Field(..., description="Average revenue per paid member")
    member_breakdown: MemberBreakdown = Field(..., description="Member breakdown details")
    
    # Content metrics
    total_content_created: int = Field(..., description="Total content created across all clubs")
    content_breakdown: ContentBreakdown = Field(..., description="Content breakdown details")
    total_partner_links: int = Field(..., description="Total partner links created")
    
    # Performance metrics
    average_club_revenue: float = Field(..., description="Average revenue per approved club")
    revenue_per_content: float = Field(..., description="Revenue per content piece")
    
    # Betting performance metrics
    total_picks: int = Field(..., description="Total picks across all clubs")
    completed_picks: int = Field(..., description="Total completed picks")
    winning_picks: int = Field(..., description="Total winning picks")
    losing_picks: int = Field(..., description="Total losing picks")
    win_percentage: float = Field(..., description="Overall win percentage")
    loss_percentage: float = Field(..., description="Overall loss percentage")
    pending_picks: int = Field(..., description="Total pending picks")


class MonthlyRevenueData(BaseModel):
    """Monthly revenue data model"""
    
    month: str = Field(..., description="Month name and year")
    year: int = Field(..., description="Year")
    month_number: int = Field(..., description="Month number (1-12)")
    captain_earnings: float = Field(..., description="Captain earnings for the month")
    platform_fees: float = Field(..., description="Platform fees for the month")
    total_revenue: float = Field(..., description="Total revenue for the month")
    transaction_count: int = Field(..., description="Number of transactions for the month")


class CaptainMonthlyRevenueResponse(BaseModel):
    """Response model for captain monthly revenue breakdown"""
    
    data: List[MonthlyRevenueData] = Field(..., description="Monthly revenue data")
    months_analyzed: int = Field(..., description="Number of months analyzed")


class ClubRevenueData(BaseModel):
    """Club revenue data model"""
    
    total_earnings: float = Field(..., description="Total captain earnings from this club")
    platform_fees: float = Field(..., description="Platform fees from this club")
    total_revenue: float = Field(..., description="Total revenue from this club")
    transaction_count: int = Field(..., description="Number of transactions for this club")


class ClubMemberData(BaseModel):
    """Club member data model"""
    
    total_members: int = Field(..., description="Total members in this club")
    paid_members: int = Field(..., description="Paid members in this club")
    trial_members: int = Field(..., description="Trial members in this club")


class ClubContentData(BaseModel):
    """Club content data model"""
    
    total_content: int = Field(..., description="Total content in this club")
    strategy_videos: int = Field(..., description="Strategy videos in this club")
    training_videos: int = Field(..., description="Training videos in this club")
    partner_links: int = Field(..., description="Partner links in this club")


class ClubBreakdownEntry(BaseModel):
    """Individual club breakdown entry"""
    
    club_id: str = Field(..., description="Club ID")
    club_name: str = Field(..., description="Club name")
    club_status: str = Field(..., description="Club status")
    created_at: str = Field(..., description="Club creation date")
    revenue: ClubRevenueData = Field(..., description="Revenue data for this club")
    members: ClubMemberData = Field(..., description="Member data for this club")
    content: ClubContentData = Field(..., description="Content data for this club")


class CaptainClubBreakdownResponse(BaseModel):
    """Response model for captain club breakdown"""
    
    data: List[ClubBreakdownEntry] = Field(..., description="Club breakdown data")
    total_clubs: int = Field(..., description="Total number of clubs")


# Recent Earnings Models
class MemberEarningsData(BaseModel):
    """Model for member earnings data in recent earnings"""
    
    user_id: str = Field(..., description="Member's user ID")
    full_name: str = Field(..., description="Member's full name")
    avatar_url: Optional[str] = Field(None, description="Member's avatar URL")
    club_id: str = Field(..., description="Club ID")
    club_name: str = Field(..., description="Club name")
    club_name_based_id: str = Field(..., description="Club name-based ID")
    membership_type: str = Field(..., description="Membership type (trial, paid)")
    pricing_plan: str = Field(..., description="Pricing plan")
    membership_status: str = Field(..., description="Membership status")
    status: str = Field(..., description="Payment status")
    payment_method: str = Field(..., description="Payment method")
    amount_paid: float = Field(..., description="Amount paid by member")
    platform_fee: float = Field(..., description="Platform fee (5%)")
    your_share: float = Field(..., description="Captain's share (95%)")
    created_at: Optional[str] = Field(None, description="When member joined")
    join_date: Optional[str] = Field(None, description="Join date")


class RecentEarningsResponse(BaseModel):
    """Response model for recent earnings API"""
    
    success: bool = Field(..., description="Whether the request was successful")
    data: List[MemberEarningsData] = Field(..., description="List of member earnings")
    pagination: Dict[str, Any] = Field(..., description="Pagination information")
    filters: Dict[str, Any] = Field(..., description="Applied filters")
    summary: Dict[str, Any] = Field(..., description="Summary statistics")


class RecentEarningsFilters(BaseModel):
    """Filters for recent earnings API"""
    
    page: int = Field(1, ge=1, description="Page number")
    limit: int = Field(20, ge=1, le=100, description="Items per page")
    club_id: Optional[str] = Field(None, description="Filter by specific club ID")
    search: Optional[str] = Field(None, description="Search by club name or member name")
    membership_type: Optional[str] = Field(None, description="Filter by membership type (trial, paid)")
    month: Optional[int] = Field(None, ge=1, le=12, description="Filter by month (1-12)")
    year: Optional[int] = Field(None, ge=2020, description="Filter by year")
    sort_by: str = Field("created_at", description="Sort field")
    sort_order: str = Field("desc", description="Sort order (asc, desc)")


class MonthlyRevenueData(BaseModel):
    """Monthly revenue data model"""
    
    month: int = Field(..., description="Month number (1-12)")
    month_name: str = Field(..., description="Month name (January, February, etc.)")
    year: int = Field(..., description="Year")
    total_revenue: float = Field(..., description="Total revenue for the month")
    old_customers_revenue: float = Field(..., description="Revenue from old customers")
    new_customers_revenue: float = Field(..., description="Revenue from new customers")
    # old_customers_count: int = Field(..., description="Number of old customers")
    # new_customers_count: int = Field(..., description="Number of new customers")
    # total_customers: int = Field(..., description="Total customers for the month")
    # old_customers_percentage: float = Field(..., description="Percentage of revenue from old customers")
    # new_customers_percentage: float = Field(..., description="Percentage of revenue from new customers")


class MonthwiseRevenueResponse(BaseModel):
    """Response model for month-wise revenue API"""
    
    success: bool = Field(..., description="Whether the request was successful")
    captain_id: str = Field(..., description="Captain ID")
    year: int = Field(..., description="Year of the data")
    monthly_data: List[MonthlyRevenueData] = Field(..., description="Monthly revenue breakdown")
    summary: Dict[str, Any] = Field(..., description="Summary statistics")
    pagination: Dict[str, Any] = Field(..., description="Pagination information")
    filters: Dict[str, Any] = Field(..., description="Applied filters")
    generated_at: str = Field(..., description="When the data was generated")