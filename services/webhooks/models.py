"""
Webhook Models

Pydantic models for webhook events and responses.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class WebhookEventType(str, Enum):
    """Stripe webhook event types"""
    # Subscriptions
    SUBSCRIPTION_CREATED = "customer.subscription.created"
    SUBSCRIPTION_UPDATED = "customer.subscription.updated"
    SUBSCRIPTION_DELETED = "customer.subscription.deleted"
    SUBSCRIPTION_TRIAL_WILL_END = "customer.subscription.trial_will_end"
    
    # Invoices
    INVOICE_PAYMENT_SUCCEEDED = "invoice.payment_succeeded"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"
    INVOICE_UPCOMING = "invoice.upcoming"
    INVOICE_FINALIZED = "invoice.finalized"
    
    # Payment Intents
    PAYMENT_INTENT_SUCCEEDED = "payment_intent.succeeded"
    PAYMENT_INTENT_FAILED = "payment_intent.payment_failed"
    PAYMENT_INTENT_CANCELED = "payment_intent.canceled"
    
    # Refunds
    CHARGE_REFUNDED = "charge.refunded"
    CHARGE_REFUND_UPDATED = "charge.refund.updated"
    
    # Connect
    ACCOUNT_UPDATED = "account.updated"
    ACCOUNT_DEAUTHORIZED = "account.application.deauthorized"
    PAYOUT_PAID = "payout.paid"
    PAYOUT_FAILED = "payout.failed"
    TRANSFER_CREATED = "transfer.created"
    TRANSFER_FAILED = "transfer.failed"


class WebhookEventLog(BaseModel):
    """Model for logging webhook events"""
    event_id: str
    event_type: str
    received_at: datetime
    processed: bool = False
    processed_at: Optional[datetime] = None
    error: Optional[str] = None
    retry_count: int = 0
    payload: Dict[str, Any]


class WebhookResponse(BaseModel):
    """Standard webhook response"""
    status: str
    message: str
    event_id: Optional[str] = None
    event_type: Optional[str] = None
    processed: bool = False


