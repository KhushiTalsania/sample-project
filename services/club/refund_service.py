"""
Refund Policy Service

This service handles the comprehensive refund policy system for club memberships.
Supports trial refunds, paid club refunds, and platform refunds with proper validation,
Stripe integration, and database management.
"""

import os
import stripe
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from .refund_models import (
    RefundRequest, RefundResponse, RefundEligibilityResponse, RefundDetails,
    RefundType, RefundStatus, RefundEligibility, RefundConfig,
    RefundHistoryResponse, RefundStatistics, RefundValidationError,
    RefundRequestValidation, RefundProcessingUpdate, RefundAdminResponse
)
from .db import get_club_collection, get_user_collection, get_membership_collection, db
from .stripe_service import StripeService

# Configure logging
logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
if not stripe.api_key:
    logger.warning("⚠️ STRIPE_SECRET_KEY not found in environment variables")

# Refund policy configuration
REFUND_CONFIG = RefundConfig(
    trial_refund_period_days=7,
    paid_refund_period_days=7,
    stripe_fee_percentage=0.029,  # 2.9%
    stripe_fee_fixed=0.30,  # $0.30
    max_refund_attempts=1,
    refund_processing_days=5,
    captain_refund_eligible=False
)

def get_refund_collection() -> AsyncIOMotorCollection:
    """Get the refunds collection"""
    return db["refunds"]

def get_refund_audit_collection() -> AsyncIOMotorCollection:
    """Get the refund audit logs collection"""
    return db["refund_audit_logs"]

class RefundService:
    """Service for handling refund operations"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
        self.membership_collection = get_membership_collection()
        self.refund_collection = get_refund_collection()
        self.audit_collection = get_refund_audit_collection()
        self.config = REFUND_CONFIG
    
    async def check_refund_eligibility(
        self, 
        user_id: str, 
        club_id: str, 
        refund_type: RefundType
    ) -> RefundEligibilityResponse:
        """
        Check if a user is eligible for a refund
        
        Args:
            user_id: User's ID
            club_id: Club ID
            refund_type: Type of refund requested
            
        Returns:
            RefundEligibilityResponse with eligibility details
        """
        try:
            logger.info(f"🔍 Checking refund eligibility for user {user_id}, club {club_id}, type {refund_type}")
            
            # Get user details
            user = await self.user_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return RefundEligibilityResponse(
                    is_eligible=False,
                    eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                    message="User not found"
                )
            
            # Check if user is a captain (captains are not eligible for refunds)
            if user.get("role") == "Captain" and not self.config.captain_refund_eligible:
                return RefundEligibilityResponse(
                    is_eligible=False,
                    eligibility_status=RefundEligibility.CAPTAIN_NOT_ELIGIBLE,
                    message="Captains are not eligible for refunds"
                )
            
            # Get club details - handle both ObjectId and name_based_id
            club = None
            try:
                # First try as ObjectId
                club = await self.club_collection.find_one({"_id": ObjectId(club_id)})
            except Exception:
                # If ObjectId fails, try as name_based_id
                club = await self.club_collection.find_one({"name_based_id": club_id})
            
            if not club:
                return RefundEligibilityResponse(
                    is_eligible=False,
                    eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                    message=f"Club not found with ID: {club_id}"
                )
            
            # Get the actual club_id (ObjectId) for database operations
            actual_club_id = str(club["_id"])
            
            # Check if user has already requested a refund for this club
            existing_refund = await self.refund_collection.find_one({
                "user_id": user_id,
                "club_id": actual_club_id,
                "refund_status": {"$in": ["pending", "approved", "processing", "completed"]}
            })
            
            if existing_refund:
                return RefundEligibilityResponse(
                    is_eligible=False,
                    eligibility_status=RefundEligibility.ALREADY_REFUNDED,
                    message="Refund already requested for this club"
                )
            
            # Find user's membership in this club
            membership = await self._find_user_membership(user_id, actual_club_id)
            if not membership:
                return RefundEligibilityResponse(
                    is_eligible=False,
                    eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                    message="User is not a member of this club"
                )
            
            # Check membership type and status
            membership_type = membership.get("membership_type", "trial")
            membership_status = membership.get("membership_status", "active")
            join_date = membership.get("join_date", membership.get("created_at"))
            
            if not join_date:
                return RefundEligibilityResponse(
                    is_eligible=False,
                    eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                    message="Invalid membership data"
                )
            
            # Calculate days since joining
            now = datetime.utcnow()
            if isinstance(join_date, str):
                join_date = datetime.fromisoformat(join_date.replace('Z', '+00:00'))
            days_since_join = (now - join_date).days
            
            # Determine refund type based on membership
            if membership_type == "trial":
                if refund_type != RefundType.TRIAL_REFUND:
                    return RefundEligibilityResponse(
                        is_eligible=False,
                        eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                        message="Invalid refund type for trial membership"
                    )
                
                # Check if within trial refund period
                if days_since_join > self.config.trial_refund_period_days:
                    return RefundEligibilityResponse(
                        is_eligible=False,
                        eligibility_status=RefundEligibility.EXPIRED,
                        message=f"Trial refund period expired. Must request within {self.config.trial_refund_period_days} days"
                    )
                
                # Calculate refund amount (platform fees only)
                platform_fee = membership.get("amount_paid", 0.0)
                if platform_fee <= 0:
                    return RefundEligibilityResponse(
                        is_eligible=False,
                        eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                        message="No platform fees paid for trial membership"
                    )
                
                stripe_fee = self._calculate_stripe_fee(platform_fee)
                net_refund = platform_fee - stripe_fee
                
                return RefundEligibilityResponse(
                    is_eligible=True,
                    eligibility_status=RefundEligibility.ELIGIBLE,
                    refund_type=RefundType.TRIAL_REFUND,
                    eligible_amount=platform_fee,
                    stripe_fee=stripe_fee,
                    net_refund=net_refund,
                    days_since_join=days_since_join,
                    refund_deadline=join_date + timedelta(days=self.config.trial_refund_period_days),
                    membership_details={
                        "membership_type": membership_type,
                        "membership_status": membership_status,
                        "join_date": join_date.isoformat(),
                        "amount_paid": platform_fee
                    },
                    message="Eligible for trial refund"
                )
            
            elif membership_type == "paid":
                if refund_type == RefundType.PAID_CLUB_REFUND:
                    # Club fee refund (non-refundable)
                    return RefundEligibilityResponse(
                        is_eligible=False,
                        eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                        message="Club joining fees are non-refundable"
                    )
                
                elif refund_type == RefundType.PLATFORM_REFUND:
                    # Platform membership refund only
                    if days_since_join > self.config.paid_refund_period_days:
                        return RefundEligibilityResponse(
                            is_eligible=False,
                            eligibility_status=RefundEligibility.EXPIRED,
                            message=f"Platform refund period expired. Must request within {self.config.paid_refund_period_days} days"
                        )
                    
                    # Calculate platform refund amount
                    platform_fee = membership.get("amount_paid", 0.0)
                    if platform_fee <= 0:
                        return RefundEligibilityResponse(
                            is_eligible=False,
                            eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                            message="No platform fees paid"
                        )
                    
                    stripe_fee = self._calculate_stripe_fee(platform_fee)
                    net_refund = platform_fee - stripe_fee
                    
                    return RefundEligibilityResponse(
                        is_eligible=True,
                        eligibility_status=RefundEligibility.ELIGIBLE,
                        refund_type=RefundType.PLATFORM_REFUND,
                        eligible_amount=platform_fee,
                        stripe_fee=stripe_fee,
                        net_refund=net_refund,
                        days_since_join=days_since_join,
                        refund_deadline=join_date + timedelta(days=self.config.paid_refund_period_days),
                        membership_details={
                            "membership_type": membership_type,
                            "membership_status": membership_status,
                            "join_date": join_date.isoformat(),
                            "amount_paid": platform_fee
                        },
                        message="Eligible for platform refund (club fees are non-refundable)"
                    )
            
            return RefundEligibilityResponse(
                is_eligible=False,
                eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                message="Invalid membership type for refund"
            )
            
        except Exception as e:
            logger.error(f"Error checking refund eligibility: {e}")
            return RefundEligibilityResponse(
                is_eligible=False,
                eligibility_status=RefundEligibility.NOT_ELIGIBLE,
                message=f"Error checking eligibility: {str(e)}"
            )
    
    async def submit_refund_request(
        self, 
        user_id: str, 
        request: RefundRequest
    ) -> Tuple[bool, Optional[RefundResponse], str]:
        """
        Submit a refund request
        
        Args:
            user_id: User's ID
            request: Refund request details
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"📝 Processing refund request for user {user_id}, club {request.club_id}")
            
            # Validate refund request
            validation = await self._validate_refund_request(user_id, request)
            if not validation.is_valid:
                error_msg = "; ".join([error.error for error in validation.errors])
                return False, None, f"Validation failed: {error_msg}"
            
            # Check eligibility
            eligibility = await self.check_refund_eligibility(user_id, request.club_id, request.refund_type)
            if not eligibility.is_eligible:
                return False, None, eligibility.message
            
            # Get user and club details - handle both ObjectId and name_based_id
            user = await self.user_collection.find_one({"_id": ObjectId(user_id)})
            
            # Get club details - handle both ObjectId and name_based_id
            club = None
            try:
                # First try as ObjectId
                club = await self.club_collection.find_one({"_id": ObjectId(request.club_id)})
            except Exception:
                # If ObjectId fails, try as name_based_id
                club = await self.club_collection.find_one({"name_based_id": request.club_id})
            
            if not club:
                return False, None, f"Club not found with ID: {request.club_id}"
            
            # Get the actual club_id (ObjectId) for database operations
            actual_club_id = str(club["_id"])
            membership = await self._find_user_membership(user_id, actual_club_id)
            
            # Create refund record
            refund_id = str(ObjectId())
            now = datetime.utcnow()
            
            refund_doc = {
                "_id": ObjectId(refund_id),
                "refund_id": refund_id,
                "user_id": user_id,
                "club_id": actual_club_id,
                "club_name": club.get("name", "Unknown Club"),
                "refund_type": request.refund_type.value,
                "refund_status": RefundStatus.PENDING.value,
                "original_amount": eligibility.eligible_amount,
                "refund_amount": eligibility.eligible_amount,
                "stripe_fee": eligibility.stripe_fee,
                "net_refund": eligibility.net_refund,
                "reason": request.reason,
                "requested_at": now,
                "refund_deadline": eligibility.refund_deadline,
                "membership_type": membership.get("membership_type", "trial"),
                "membership_status": membership.get("membership_status", "active"),
                "join_date": membership.get("join_date", membership.get("created_at")),
                "is_one_time_refund": True,
                "created_at": now,
                "updated_at": now
            }
            
            # Insert refund record
            await self.refund_collection.insert_one(refund_doc)
            
            # Create audit log
            await self._create_audit_log(
                refund_id=refund_id,
                action="refund_requested",
                performed_by=user_id,
                old_status=None,
                new_status=RefundStatus.PENDING,
                changes={"refund_type": request.refund_type.value}
            )
            
            # Create response
            response = RefundResponse(
                success=True,
                message="Refund request submitted successfully",
                refund_id=refund_id,
                refund_status=RefundStatus.PENDING,
                refund_amount=eligibility.eligible_amount,
                stripe_fee=eligibility.stripe_fee,
                net_refund=eligibility.net_refund,
                estimated_processing_time=f"{self.config.refund_processing_days} business days"
            )
            
            logger.info(f"✅ Refund request submitted successfully: {refund_id}")
            return True, response, ""
            
        except Exception as e:
            logger.error(f"Error submitting refund request: {e}")
            return False, None, f"Error submitting refund request: {str(e)}"
    
    async def process_refund(
        self, 
        refund_id: str, 
        admin_id: str
    ) -> Tuple[bool, Optional[RefundResponse], str]:
        """
        Process an approved refund through Stripe
        
        Args:
            refund_id: Refund ID to process
            admin_id: Admin processing the refund
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"🔄 Processing refund: {refund_id}")
            
            # Get refund details
            refund = await self.refund_collection.find_one({"refund_id": refund_id})
            if not refund:
                return False, None, "Refund not found"
            
            if refund["refund_status"] != RefundStatus.APPROVED.value:
                return False, None, f"Refund must be approved before processing. Current status: {refund['refund_status']}"
            
            # Get user details for Stripe customer
            user = await self.user_collection.find_one({"_id": ObjectId(refund["user_id"])})
            if not user:
                return False, None, "User not found"
            
            # Process Stripe refund
            stripe_refund_id = None
            try:
                # Get payment intent ID from membership
                membership = await self._find_user_membership(refund["user_id"], refund["club_id"])
                payment_id = membership.get("payment_id")
                
                if not payment_id:
                    return False, None, "Payment ID not found for refund processing"
                
                # Create Stripe refund
                stripe_refund = stripe.Refund.create(
                    payment_intent=payment_id,
                    amount=int(refund["net_refund"] * 100),  # Convert to cents
                    reason="requested_by_customer",
                    metadata={
                        "refund_type": "club_member_refund",  # Standard format
                        "service": "club",  # Standard format
                        "refund_id": refund_id,
                        "user_id": refund["user_id"],
                        "club_id": refund["club_id"],
                        "payment_type": "refund"  # Standard format
                    }
                )
                
                stripe_refund_id = stripe_refund.id
                logger.info(f"✅ Stripe refund created: {stripe_refund_id}")
                
            except stripe.error.StripeError as e:
                logger.error(f"Stripe refund error: {e}")
                return False, None, f"Stripe refund failed: {str(e)}"
            
            # Update refund status
            now = datetime.utcnow()
            await self.refund_collection.update_one(
                {"refund_id": refund_id},
                {
                    "$set": {
                        "refund_status": RefundStatus.PROCESSING.value,
                        "stripe_refund_id": stripe_refund_id,
                        "processed_at": now,
                        "updated_at": now
                    }
                }
            )
            
            # Update membership status
            await self._update_membership_status(
                refund["user_id"], 
                refund["club_id"], 
                "inactive"
            )
            
            # Create audit log
            await self._create_audit_log(
                refund_id=refund_id,
                action="refund_processing_started",
                performed_by=admin_id,
                old_status=RefundStatus.APPROVED,
                new_status=RefundStatus.PROCESSING,
                changes={"stripe_refund_id": stripe_refund_id}
            )
            
            # Create response
            response = RefundResponse(
                success=True,
                message="Refund processing started",
                refund_id=refund_id,
                refund_status=RefundStatus.PROCESSING,
                refund_amount=refund["refund_amount"],
                stripe_fee=refund["stripe_fee"],
                net_refund=refund["net_refund"],
                processed_at=now
            )
            
            logger.info(f"✅ Refund processing started: {refund_id}")
            return True, response, ""
            
        except Exception as e:
            logger.error(f"Error processing refund: {e}")
            return False, None, f"Error processing refund: {str(e)}"
    
    async def approve_refund(
        self, 
        refund_id: str, 
        admin_id: str, 
        admin_notes: Optional[str] = None
    ) -> Tuple[bool, Optional[RefundAdminResponse], str]:
        """
        Approve a refund request
        
        Args:
            refund_id: Refund ID to approve
            admin_id: Admin approving the refund
            admin_notes: Optional admin notes
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"✅ Approving refund: {refund_id}")
            
            # Get refund details
            refund = await self.refund_collection.find_one({"refund_id": refund_id})
            if not refund:
                return False, None, "Refund not found"
            
            if refund["refund_status"] != RefundStatus.PENDING.value:
                return False, None, f"Refund must be pending for approval. Current status: {refund['refund_status']}"
            
            # Update refund status
            now = datetime.utcnow()
            await self.refund_collection.update_one(
                {"refund_id": refund_id},
                {
                    "$set": {
                        "refund_status": RefundStatus.APPROVED.value,
                        "admin_notes": admin_notes,
                        "approved_by": admin_id,
                        "approved_at": now,
                        "updated_at": now
                    }
                }
            )
            
            # Create audit log
            await self._create_audit_log(
                refund_id=refund_id,
                action="refund_approved",
                performed_by=admin_id,
                old_status=RefundStatus.PENDING,
                new_status=RefundStatus.APPROVED,
                changes={"admin_notes": admin_notes}
            )
            
            # Create response
            response = RefundAdminResponse(
                success=True,
                message="Refund approved successfully",
                refund_id=refund_id,
                updated_status=RefundStatus.APPROVED,
                action_taken="approved",
                processed_at=now
            )
            
            logger.info(f"✅ Refund approved: {refund_id}")
            return True, response, ""
            
        except Exception as e:
            logger.error(f"Error approving refund: {e}")
            return False, None, f"Error approving refund: {str(e)}"
    
    async def reject_refund(
        self, 
        refund_id: str, 
        admin_id: str, 
        rejection_reason: str,
        admin_notes: Optional[str] = None
    ) -> Tuple[bool, Optional[RefundAdminResponse], str]:
        """
        Reject a refund request
        
        Args:
            refund_id: Refund ID to reject
            admin_id: Admin rejecting the refund
            rejection_reason: Reason for rejection
            admin_notes: Optional admin notes
            
        Returns:
            Tuple of (success, response_data, error_message)
        """
        try:
            logger.info(f"❌ Rejecting refund: {refund_id}")
            
            # Get refund details
            refund = await self.refund_collection.find_one({"refund_id": refund_id})
            if not refund:
                return False, None, "Refund not found"
            
            if refund["refund_status"] != RefundStatus.PENDING.value:
                return False, None, f"Refund must be pending for rejection. Current status: {refund['refund_status']}"
            
            # Update refund status
            now = datetime.utcnow()
            await self.refund_collection.update_one(
                {"refund_id": refund_id},
                {
                    "$set": {
                        "refund_status": RefundStatus.REJECTED.value,
                        "rejection_reason": rejection_reason,
                        "admin_notes": admin_notes,
                        "rejected_by": admin_id,
                        "rejected_at": now,
                        "updated_at": now
                    }
                }
            )
            
            # Create audit log
            await self._create_audit_log(
                refund_id=refund_id,
                action="refund_rejected",
                performed_by=admin_id,
                old_status=RefundStatus.PENDING,
                new_status=RefundStatus.REJECTED,
                changes={"rejection_reason": rejection_reason, "admin_notes": admin_notes}
            )
            
            # Create response
            response = RefundAdminResponse(
                success=True,
                message="Refund rejected",
                refund_id=refund_id,
                updated_status=RefundStatus.REJECTED,
                action_taken="rejected",
                processed_at=now
            )
            
            logger.info(f"✅ Refund rejected: {refund_id}")
            return True, response, ""
            
        except Exception as e:
            logger.error(f"Error rejecting refund: {e}")
            return False, None, f"Error rejecting refund: {str(e)}"
    
    async def get_refund_history(
        self, 
        user_id: str, 
        limit: int = 50, 
        offset: int = 0
    ) -> RefundHistoryResponse:
        """
        Get refund history for a user
        
        Args:
            user_id: User's ID
            limit: Number of records to return
            offset: Number of records to skip
            
        Returns:
            RefundHistoryResponse with refund history
        """
        try:
            logger.info(f"📋 Getting refund history for user: {user_id}")
            
            # Get refunds for user
            refunds_cursor = self.refund_collection.find(
                {"user_id": user_id}
            ).sort("requested_at", -1).skip(offset).limit(limit)
            
            refunds = await refunds_cursor.to_list(length=limit)
            
            # Convert to RefundDetails objects
            refund_details = []
            total_refunded = 0.0
            pending_count = 0
            completed_count = 0
            
            for refund in refunds:
                refund_detail = RefundDetails(
                    refund_id=refund["refund_id"],
                    user_id=refund["user_id"],
                    club_id=refund["club_id"],
                    club_name=refund["club_name"],
                    refund_type=RefundType(refund["refund_type"]),
                    refund_status=RefundStatus(refund["refund_status"]),
                    original_amount=refund["original_amount"],
                    refund_amount=refund["refund_amount"],
                    stripe_fee=refund["stripe_fee"],
                    net_refund=refund["net_refund"],
                    reason=refund.get("reason"),
                    requested_at=refund["requested_at"],
                    processed_at=refund.get("processed_at"),
                    stripe_refund_id=refund.get("stripe_refund_id"),
                    membership_type=refund["membership_type"],
                    membership_status=refund["membership_status"],
                    join_date=refund["join_date"],
                    refund_deadline=refund["refund_deadline"],
                    is_one_time_refund=refund.get("is_one_time_refund", True)
                )
                
                refund_details.append(refund_detail)
                
                # Calculate statistics
                if refund["refund_status"] == RefundStatus.COMPLETED.value:
                    total_refunded += refund["net_refund"]
                    completed_count += 1
                elif refund["refund_status"] in [RefundStatus.PENDING.value, RefundStatus.APPROVED.value, RefundStatus.PROCESSING.value]:
                    pending_count += 1
            
            # Get total count
            total_count = await self.refund_collection.count_documents({"user_id": user_id})
            
            return RefundHistoryResponse(
                refunds=refund_details,
                total_count=total_count,
                total_refunded=total_refunded,
                pending_count=pending_count,
                completed_count=completed_count
            )
            
        except Exception as e:
            logger.error(f"Error getting refund history: {e}")
            return RefundHistoryResponse(
                refunds=[],
                total_count=0,
                total_refunded=0.0,
                pending_count=0,
                completed_count=0
            )
    
    async def _find_user_membership(self, user_id: str, club_id: str) -> Optional[Dict[str, Any]]:
        """Find user's membership in a specific club"""
        try:
            # Check in club's members array
            club = await self.club_collection.find_one({
                "_id": ObjectId(club_id),
                "$or": [
                    {"members.user_id": user_id},
                    {"paid_members.user_id": user_id}
                ]
            })
            
            if club:
                # Find the specific member
                for member in club.get("members", []):
                    if member.get("user_id") == user_id:
                        return member
                
                for member in club.get("paid_members", []):
                    if member.get("user_id") == user_id:
                        return member
            
            # Check in memberships collection
            membership = await self.membership_collection.find_one({
                "user_id": user_id,
                "club_id": club_id,
                "status": {"$in": ["active", "trial", "pending"]}
            })
            
            return membership
            
        except Exception as e:
            logger.error(f"Error finding user membership: {e}")
            return None
    
    async def _update_membership_status(
        self, 
        user_id: str, 
        club_id: str, 
        status: str
    ) -> bool:
        """Update membership status after refund"""
        try:
            # Update in club's members/paid_members arrays
            club = await self.club_collection.find_one({
                "_id": ObjectId(club_id),
                "$or": [
                    {"members.user_id": user_id},
                    {"paid_members.user_id": user_id}
                ]
            })
            
            if club:
                # Update members array
                await self.club_collection.update_one(
                    {"_id": ObjectId(club_id), "members.user_id": user_id},
                    {
                        "$set": {
                            "members.$.membership_status": status,
                            "members.$.is_active": False,
                            "members.$.updated_at": datetime.utcnow()
                        }
                    }
                )
                
                # Update paid_members array
                await self.club_collection.update_one(
                    {"_id": ObjectId(club_id), "paid_members.user_id": user_id},
                    {
                        "$set": {
                            "paid_members.$.membership_status": status,
                            "paid_members.$.is_active": False,
                            "paid_members.$.updated_at": datetime.utcnow()
                        }
                    }
                )
            
            # Update in memberships collection
            await self.membership_collection.update_one(
                {"user_id": user_id, "club_id": club_id},
                {
                    "$set": {
                        "status": status,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            # Update in user's clubs_joined array
            await self.user_collection.update_one(
                {"_id": ObjectId(user_id), "clubs_joined.club_id": club_id},
                {
                    "$set": {
                        "clubs_joined.$.membership_status": status,
                        "clubs_joined.$.is_active": False,
                        "clubs_joined.$.updated_at": datetime.utcnow()
                    }
                }
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating membership status: {e}")
            return False
    
    def _calculate_stripe_fee(self, amount: float) -> float:
        """Calculate Stripe processing fee"""
        return (amount * self.config.stripe_fee_percentage) + self.config.stripe_fee_fixed
    
    async def _validate_refund_request(
        self, 
        user_id: str, 
        request: RefundRequest
    ) -> RefundRequestValidation:
        """Validate refund request"""
        errors = []
        warnings = []
        
        # Validate club_id
        if not request.club_id:
            errors.append(RefundValidationError(
                field="club_id",
                error="Club ID is required",
                value=request.club_id
            ))
        
        # Validate refund_type
        if not request.refund_type:
            errors.append(RefundValidationError(
                field="refund_type",
                error="Refund type is required",
                value=request.refund_type
            ))
        
        # Validate reason length
        if request.reason and len(request.reason) > 500:
            errors.append(RefundValidationError(
                field="reason",
                error="Reason must be 500 characters or less",
                value=request.reason
            ))
        
        # Validate refund_amount if provided
        if request.refund_amount is not None and request.refund_amount < 0:
            errors.append(RefundValidationError(
                field="refund_amount",
                error="Refund amount must be positive",
                value=request.refund_amount
            ))
        
        return RefundRequestValidation(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    async def _create_audit_log(
        self,
        refund_id: str,
        action: str,
        performed_by: str,
        old_status: Optional[RefundStatus] = None,
        new_status: Optional[RefundStatus] = None,
        changes: Optional[Dict[str, Any]] = None
    ) -> None:
        """Create audit log entry"""
        try:
            audit_doc = {
                "_id": ObjectId(),
                "refund_id": refund_id,
                "action": action,
                "performed_by": performed_by,
                "performed_at": datetime.utcnow(),
                "old_status": old_status.value if old_status else None,
                "new_status": new_status.value if new_status else None,
                "changes": changes or {},
                "created_at": datetime.utcnow()
            }
            
            await self.audit_collection.insert_one(audit_doc)
            
        except Exception as e:
            logger.error(f"Error creating audit log: {e}")
    
    async def get_refund_statistics(self) -> RefundStatistics:
        """Get refund statistics for admin dashboard"""
        try:
            # Get all refunds
            all_refunds = await self.refund_collection.find({}).to_list(None)
            
            total_refunds_requested = len(all_refunds)
            total_refunds_processed = len([r for r in all_refunds if r["refund_status"] == RefundStatus.COMPLETED.value])
            total_amount_refunded = sum([r["net_refund"] for r in all_refunds if r["refund_status"] == RefundStatus.COMPLETED.value])
            total_stripe_fees = sum([r["stripe_fee"] for r in all_refunds if r["refund_status"] == RefundStatus.COMPLETED.value])
            
            average_refund_amount = total_amount_refunded / total_refunds_processed if total_refunds_processed > 0 else 0
            refund_success_rate = (total_refunds_processed / total_refunds_requested * 100) if total_refunds_requested > 0 else 0
            
            trial_refunds = len([r for r in all_refunds if r["refund_type"] == RefundType.TRIAL_REFUND.value])
            paid_refunds = len([r for r in all_refunds if r["refund_type"] == RefundType.PAID_CLUB_REFUND.value])
            platform_refunds = len([r for r in all_refunds if r["refund_type"] == RefundType.PLATFORM_REFUND.value])
            
            return RefundStatistics(
                total_refunds_requested=total_refunds_requested,
                total_refunds_processed=total_refunds_processed,
                total_amount_refunded=total_amount_refunded,
                total_stripe_fees=total_stripe_fees,
                average_refund_amount=average_refund_amount,
                refund_success_rate=refund_success_rate,
                trial_refunds=trial_refunds,
                paid_refunds=paid_refunds,
                platform_refunds=platform_refunds
            )
            
        except Exception as e:
            logger.error(f"Error getting refund statistics: {e}")
            return RefundStatistics(
                total_refunds_requested=0,
                total_refunds_processed=0,
                total_amount_refunded=0.0,
                total_stripe_fees=0.0,
                average_refund_amount=0.0,
                refund_success_rate=0.0,
                trial_refunds=0,
                paid_refunds=0,
                platform_refunds=0
            )
