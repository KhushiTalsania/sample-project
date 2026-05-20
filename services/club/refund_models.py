"""
Refund Policy Models

This module defines the Pydantic models for the refund policy system.
Handles refund requests, responses, and tracking for both trial and paid memberships.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class RefundType(str, Enum):
    """Types of refunds available"""
    TRIAL_REFUND = "trial_refund"  # Full refund for trial members (platform fees only)
    PAID_CLUB_REFUND = "paid_club_refund"  # Club fee refund (non-refundable)
    PLATFORM_REFUND = "platform_refund"  # Platform membership refund only

class RefundStatus(str, Enum):
    """Status of refund requests"""
    PENDING = "pending"
    APPROVED = "approved"
    PROCESSING = "processing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

class RefundEligibility(str, Enum):
    """Refund eligibility status"""
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    ALREADY_REFUNDED = "already_refunded"
    EXPIRED = "expired"
    CAPTAIN_NOT_ELIGIBLE = "captain_not_eligible"

class RefundRequest(BaseModel):
    """Request model for refund submission"""
    club_id: str = Field(..., description="Club ID for which refund is requested")
    refund_type: RefundType = Field(..., description="Type of refund requested")
    reason: Optional[str] = Field(None, max_length=500, description="Reason for refund request")
    refund_amount: Optional[float] = Field(None, ge=0, description="Requested refund amount (optional)")

class RefundResponse(BaseModel):
    """Response model for refund operations"""
    success: bool
    message: str
    refund_id: Optional[str] = None
    refund_status: Optional[RefundStatus] = None
    refund_amount: Optional[float] = None
    stripe_fee: Optional[float] = None
    net_refund: Optional[float] = None
    processed_at: Optional[datetime] = None
    estimated_processing_time: Optional[str] = None

class RefundEligibilityResponse(BaseModel):
    """Response model for refund eligibility check"""
    is_eligible: bool
    eligibility_status: RefundEligibility
    refund_type: Optional[RefundType] = None
    eligible_amount: Optional[float] = None
    stripe_fee: Optional[float] = None
    net_refund: Optional[float] = None
    days_since_join: Optional[int] = None
    refund_deadline: Optional[datetime] = None
    membership_details: Optional[Dict[str, Any]] = None
    message: str

class RefundDetails(BaseModel):
    """Detailed refund information"""
    refund_id: str
    user_id: str
    club_id: str
    club_name: str
    refund_type: RefundType
    refund_status: RefundStatus
    original_amount: float
    refund_amount: float
    stripe_fee: float
    net_refund: float
    reason: Optional[str] = None
    requested_at: datetime
    processed_at: Optional[datetime] = None
    stripe_refund_id: Optional[str] = None
    membership_type: str  # "trial" or "paid"
    membership_status: str  # "active" or "inactive"
    join_date: datetime
    refund_deadline: datetime
    is_one_time_refund: bool = True  # Users can only refund once

class RefundHistoryResponse(BaseModel):
    """Response model for refund history"""
    refunds: List[RefundDetails]
    total_count: int
    total_refunded: float
    pending_count: int
    completed_count: int

class RefundStatistics(BaseModel):
    """Refund statistics for admin/captain view"""
    total_refunds_requested: int
    total_refunds_processed: int
    total_amount_refunded: float
    total_stripe_fees: float
    average_refund_amount: float
    refund_success_rate: float
    trial_refunds: int
    paid_refunds: int
    platform_refunds: int

class RefundConfig(BaseModel):
    """Refund policy configuration"""
    trial_refund_period_days: int = 7
    paid_refund_period_days: int = 7
    stripe_fee_percentage: float = 0.029  # 2.9% + $0.30
    stripe_fee_fixed: float = 0.30
    max_refund_attempts: int = 1
    refund_processing_days: int = 5
    captain_refund_eligible: bool = False

class RefundWebhookData(BaseModel):
    """Data structure for refund webhook events"""
    event_type: str
    refund_id: str
    status: str
    amount: float
    currency: str
    stripe_refund_id: str
    processed_at: datetime
    failure_reason: Optional[str] = None

class RefundValidationError(BaseModel):
    """Validation error for refund requests"""
    field: str
    error: str
    value: Any

class RefundRequestValidation(BaseModel):
    """Validation result for refund requests"""
    is_valid: bool
    errors: List[RefundValidationError] = []
    warnings: List[str] = []
    eligibility: Optional[RefundEligibilityResponse] = None

class RefundProcessingUpdate(BaseModel):
    """Update model for refund processing status"""
    refund_id: str
    status: RefundStatus
    stripe_refund_id: Optional[str] = None
    processed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    admin_notes: Optional[str] = None

class RefundAdminResponse(BaseModel):
    """Admin response for refund management"""
    success: bool
    message: str
    refund_id: str
    updated_status: RefundStatus
    action_taken: str
    processed_at: Optional[datetime] = None

class RefundNotification(BaseModel):
    """Notification model for refund status updates"""
    user_id: str
    refund_id: str
    club_name: str
    status: RefundStatus
    amount: float
    message: str
    notification_type: str  # "refund_approved", "refund_processed", "refund_rejected", etc.
    sent_at: datetime

class RefundAnalytics(BaseModel):
    """Analytics data for refund patterns"""
    period_start: datetime
    period_end: datetime
    total_requests: int
    approval_rate: float
    average_processing_time_hours: float
    most_common_reasons: List[Dict[str, Any]]
    club_refund_rates: Dict[str, float]
    user_refund_patterns: Dict[str, Any]

class RefundDispute(BaseModel):
    """Dispute model for refund conflicts"""
    dispute_id: str
    refund_id: str
    user_id: str
    club_id: str
    dispute_reason: str
    dispute_details: str
    created_at: datetime
    status: str  # "open", "resolved", "escalated"
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None
    admin_notes: Optional[str] = None

class RefundAuditLog(BaseModel):
    """Audit log for refund actions"""
    log_id: str
    refund_id: str
    action: str
    performed_by: str  # user_id or admin_id
    performed_at: datetime
    old_status: Optional[RefundStatus] = None
    new_status: Optional[RefundStatus] = None
    changes: Dict[str, Any] = {}
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    notes: Optional[str] = None

class RefundPolicyInfo(BaseModel):
    """Information about refund policy for users"""
    trial_refund_policy: str
    paid_refund_policy: str
    platform_refund_policy: str
    refund_deadline_days: int
    stripe_fee_info: str
    processing_time_info: str
    contact_info: str
    terms_url: str
    faq_url: str

class RefundBulkAction(BaseModel):
    """Bulk action model for processing multiple refunds"""
    action: str  # "approve", "reject", "process"
    refund_ids: List[str]
    reason: Optional[str] = None
    admin_notes: Optional[str] = None

class RefundBulkResponse(BaseModel):
    """Response for bulk refund actions"""
    success: bool
    processed_count: int
    failed_count: int
    results: List[Dict[str, Any]]
    errors: List[str] = []
    message: str

class RefundExportData(BaseModel):
    """Data model for refund export"""
    export_id: str
    created_at: datetime
    period_start: datetime
    period_end: datetime
    total_records: int
    file_url: Optional[str] = None
    status: str  # "processing", "completed", "failed"
    error_message: Optional[str] = None

class RefundMetrics(BaseModel):
    """Metrics for refund dashboard"""
    total_refunds_today: int
    total_refunds_this_week: int
    total_refunds_this_month: int
    pending_refunds: int
    processing_refunds: int
    completed_refunds: int
    rejected_refunds: int
    total_amount_refunded_today: float
    total_amount_refunded_this_week: float
    total_amount_refunded_this_month: float
    average_refund_amount: float
    refund_trends: Dict[str, Any]
    top_refund_reasons: List[Dict[str, Any]]
    club_refund_rates: List[Dict[str, Any]]
