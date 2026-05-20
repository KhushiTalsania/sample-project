"""
Centralized Authentication Routes

This module combines all authentication routes using centralized components.
All routes maintain exact same API compatibility as the original microservice.
"""

from fastapi import APIRouter

# Import all route modules (including webhooks for completeness)
from .routes.registration import router as registration_router
from .routes.login import router as login_router
from .routes.email_login import router as email_login_router
from .routes.password_reset import router as password_reset_router
from .routes.social_login import router as social_login_router
from .routes.trial_membership import router as trial_membership_router
from .routes.moderator_membership import router as moderator_membership_router
from .routes.my_profile import router as my_profile_router
from .routes.webhooks import router as webhook_router
from .routes.refund import router as refund_router
from .routes.order_history import router as order_history_router
from .routes.joined_clubs import router as joined_clubs_router
from .routes.support_feedback import router as support_feedback_router
from .routes.captain_members import router as captain_members_router
from .routes.account_deletion import router as account_deletion_router
from .routes.member_details import router as member_details_router
from .routes.member_deletion import router as member_deletion_router
from .routes.stripe_webhooks import router as stripe_webhooks_router

# Create main auth router
router = APIRouter()

# Include all sub-routers with EXACT same prefixes as microservice
router.include_router(registration_router, prefix="/auth", tags=["Registration"])
router.include_router(login_router, prefix="/auth", tags=["OTP Login"])
router.include_router(email_login_router, prefix="/auth", tags=["Email Login"])
router.include_router(password_reset_router, prefix="/auth", tags=["Password Reset"])
router.include_router(social_login_router, tags=["Social Login"])
router.include_router(trial_membership_router, tags=["Trial Membership"])
router.include_router(moderator_membership_router, tags=["Moderator Membership"])
router.include_router(my_profile_router, prefix="/auth", tags=["User Profile"])
router.include_router(refund_router, prefix="/auth", tags=["Refunds"])
router.include_router(order_history_router, prefix="/auth", tags=["Order History"])
router.include_router(joined_clubs_router, prefix="/auth", tags=["Joined Clubs"])
router.include_router(
    support_feedback_router, prefix="/auth", tags=["Support & Feedback"]
)
router.include_router(captain_members_router, prefix="/auth", tags=["Captain Members"])
router.include_router(
    account_deletion_router, prefix="/auth", tags=["Account Deletion"]
)
router.include_router(member_details_router, prefix="/auth", tags=["Member Details"])
router.include_router(member_deletion_router, prefix="/auth", tags=["Member Deletion"])
router.include_router(stripe_webhooks_router, prefix="/auth", tags=["Stripe Webhooks"])
# Note: webhooks router was commented in original microservice, keeping same behavior
# router.include_router(webhook_router, tags=["Webhooks"])
