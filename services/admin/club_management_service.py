"""
Club Management Service

This service handles advanced club management operations including:
- Club approval/rejection with email notifications
- Club activity monitoring and health status
- Club picks management and analytics
- Performance tracking and recommendations
"""

import time
import stripe
import os
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from bson import ObjectId
from services.admin.utils.email import send_email

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
from .db import (
    clubs_collection, club_memberships_collection, users_collection,
    club_picks_collection, club_activity_collection, club_admin_logs_collection,
    club_payments_collection
)
from .models import (
    ClubApprovalRequest, ClubApprovalResponse, ClubApprovalStatus,
    ClubMonitoringResponse, ClubActivityMetrics, ClubPerformanceSummary,
    ClubHealthStatus, ActivityPeriod, ClubPicksRequest, ClubPicksResponse,
    ClubPickItem, ClubPicksPagination, ClubPicksSummary, PickStatus,
    PickType, SubmittedByRole, SortOrder
)

class AdminClubManagementService:
    def __init__(self):
        self.clubs_collection = clubs_collection
        self.club_memberships_collection = club_memberships_collection
        self.users_collection = users_collection
        self.club_picks_collection = club_picks_collection
        self.club_activity_collection = club_activity_collection
        self.club_admin_logs_collection = club_admin_logs_collection
        self.club_payments_collection = club_payments_collection

    # ========================================
    # Club Approval/Rejection Service
    # ========================================

    async def approve_reject_club(self, club_id: str, request: ClubApprovalRequest, 
                                admin_email: str, ip_address: Optional[str] = None) -> ClubApprovalResponse:
        """
        Approve or reject a club with email notification
        
        Args:
            club_id: Club ID to approve/reject
            request: ClubApprovalRequest with status and details
            admin_email: Email of admin performing the action
            ip_address: IP address for audit logging
            
        Returns:
            ClubApprovalResponse with operation results
        """
        try:
            print(f"DEBUG: Processing club {request.status.value} for club {club_id}")
            
            # Validate club exists
            club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club_doc:
                return ClubApprovalResponse(
                    success=False,
                    message="Club not found",
                    club_id=club_id,
                    previous_status="unknown",
                    new_status=request.status.value,
                    notification_sent=False,
                    admin_email=admin_email,
                    timestamp=datetime.utcnow(),
                    approval_id=""
                )
            
            previous_status = club_doc.get("status", "unknown")
            
            # Get club owner details for email notification
            captain_id = club_doc.get("captain_id")
            owner_doc = None
            owner_email = None
            
            if captain_id:
                owner_doc = await self.users_collection.find_one({"_id": ObjectId(captain_id)})
                if owner_doc:
                    owner_email = owner_doc.get("email")
            
            # Update club status based on rejection type
            update_data = {
                "status": request.status.value,
                "updated_at": datetime.utcnow(),
                "updated_by_admin": admin_email
            }
            
            if request.admin_notes:
                update_data["admin_notes"] = request.admin_notes
                
            if request.status == ClubApprovalStatus.APPROVED:
                update_data["approved_at"] = datetime.utcnow()
                update_data["approved_by"] = admin_email
                update_data["is_resubmit"] = False
                update_data["is_club_reject_permanently"] = False
                update_data["is_club_reject_temporary"] = False
                
                # 💳 CHARGE THE PAYMENT NOW (after admin approval)
                payment_intent_id = club_doc.get("payment_intent_id")
                if payment_intent_id:
                    try:
                        print(f"💰 Admin approved club - charging payment intent: {payment_intent_id}")
                        
                        # Confirm/capture the payment intent
                        payment_intent = stripe.PaymentIntent.confirm(payment_intent_id)
                        
                        if payment_intent.status == "succeeded":
                            print(f"✅ Payment charged successfully: ${payment_intent.amount / 100}")
                            update_data["payment_status"] = "succeeded"
                            update_data["payment_confirmed_at"] = datetime.utcnow()
                            
                            # Update payment record in club_payments
                            await self.club_payments_collection.update_one(
                                {"payment_intent_id": payment_intent_id},
                                {"$set": {
                                    "payment_status": "succeeded",
                                    "charged_at": datetime.utcnow(),
                                    "charged_by_admin": admin_email,
                                    "updated_at": datetime.utcnow()
                                }}
                            )
                        else:
                            print(f"⚠️ Payment confirmation returned status: {payment_intent.status}")
                            update_data["payment_status"] = payment_intent.status
                            
                    except stripe.error.CardError as e:
                        # Card was declined
                        print(f"❌ Card declined when charging: {e.user_message}")
                        update_data["payment_status"] = "failed"
                        update_data["payment_error"] = e.user_message
                        
                    except Exception as e:
                        print(f"❌ Error charging payment: {str(e)}")
                        update_data["payment_status"] = "error"
                        update_data["payment_error"] = str(e)
                else:
                    print(f"ℹ️ No payment intent found for club {club_id} (might be free club)")
                
            elif request.status == ClubApprovalStatus.REJECTED_TEMPORARY:
                # Temporary rejection - set status to rejected for resubmission
                update_data["status"] = "rejected"  # Set to rejected for temporary rejection
                update_data["rejected_at"] = datetime.utcnow()
                update_data["rejected_by"] = admin_email
                update_data["rejection_reason"] = request.reason
                update_data["rejection_type"] = "temporary"
                update_data["is_resubmit"] = True
                update_data["is_club_reject_permanently"] = False
                update_data["is_club_reject_temporary"] = True
                
            elif request.status == ClubApprovalStatus.REJECTED_PERMANENT:
                # Permanent rejection - delete club and cancel payment
                update_data["status"] = "deleted"
                update_data["rejected_at"] = datetime.utcnow()
                update_data["rejected_by"] = admin_email
                update_data["rejection_reason"] = request.reason
                update_data["rejection_type"] = "permanent"
                update_data["is_resubmit"] = False
                update_data["is_club_reject_permanently"] = True
                update_data["is_club_reject_temporary"] = False
                update_data["deleted_at"] = datetime.utcnow()
                update_data["deleted_by"] = admin_email
                
                # ❌ CANCEL THE PAYMENT (release hold immediately)
                payment_intent_id = club_doc.get("payment_intent_id")
                if payment_intent_id:
                    try:
                        print(f"❌ Admin permanently rejected club - canceling payment intent: {payment_intent_id}")
                        
                        # Cancel the payment intent (releases the hold)
                        payment_intent = stripe.PaymentIntent.cancel(payment_intent_id)
                        
                        if payment_intent.status == "canceled":
                            print(f"✅ Payment canceled successfully - money released back to customer")
                            update_data["payment_status"] = "canceled"
                            update_data["payment_canceled_at"] = datetime.utcnow()
                            
                            # Update payment record in club_payments
                            await self.club_payments_collection.update_one(
                                {"payment_intent_id": payment_intent_id},
                                {"$set": {
                                    "payment_status": "canceled",
                                    "canceled_at": datetime.utcnow(),
                                    "canceled_by_admin": admin_email,
                                    "cancellation_reason": request.reason,
                                    "updated_at": datetime.utcnow()
                                }}
                            )
                        else:
                            print(f"⚠️ Payment cancellation returned status: {payment_intent.status}")
                            update_data["payment_status"] = payment_intent.status
                            
                    except Exception as e:
                        print(f"❌ Error canceling payment: {str(e)}")
                        # If payment can't be canceled, try to refund instead
                        print(f"⚠️ Attempting refund as fallback...")
                        update_data["payment_status"] = "cancellation_failed"
                        update_data["payment_error"] = str(e)
                else:
                    print(f"ℹ️ No payment intent found for club {club_id} (might be free club)")
                
            elif request.status == ClubApprovalStatus.REJECTED:
                # Legacy rejection - treat as permanent
                update_data["status"] = "deleted"
                update_data["rejected_at"] = datetime.utcnow()
                update_data["rejected_by"] = admin_email
                update_data["rejection_reason"] = request.reason
                update_data["rejection_type"] = "permanent"
                update_data["is_resubmit"] = False
                update_data["is_club_reject_permanently"] = True
                update_data["is_club_reject_temporary"] = False
                update_data["deleted_at"] = datetime.utcnow()
                update_data["deleted_by"] = admin_email
                
                # ❌ CANCEL THE PAYMENT (release hold immediately)
                payment_intent_id = club_doc.get("payment_intent_id")
                if payment_intent_id:
                    try:
                        print(f"❌ Admin rejected club - canceling payment intent: {payment_intent_id}")
                        
                        # Cancel the payment intent (releases the hold)
                        payment_intent = stripe.PaymentIntent.cancel(payment_intent_id)
                        
                        if payment_intent.status == "canceled":
                            print(f"✅ Payment canceled successfully - money released back to customer")
                            update_data["payment_status"] = "canceled"
                            update_data["payment_canceled_at"] = datetime.utcnow()
                            
                            # Update payment record in club_payments
                            await self.club_payments_collection.update_one(
                                {"payment_intent_id": payment_intent_id},
                                {"$set": {
                                    "payment_status": "canceled",
                                    "canceled_at": datetime.utcnow(),
                                    "canceled_by_admin": admin_email,
                                    "cancellation_reason": request.reason,
                                    "updated_at": datetime.utcnow()
                                }}
                            )
                        else:
                            print(f"⚠️ Payment cancellation returned status: {payment_intent.status}")
                            update_data["payment_status"] = payment_intent.status
                            
                    except Exception as e:
                        print(f"❌ Error canceling payment: {str(e)}")
                        # If payment can't be canceled, try to refund instead
                        print(f"⚠️ Attempting refund as fallback...")
                        update_data["payment_status"] = "cancellation_failed"
                        update_data["payment_error"] = str(e)
                else:
                    print(f"ℹ️ No payment intent found for club {club_id} (might be free club)")
            
            await self.clubs_collection.update_one(
                {"_id": ObjectId(club_id)},
                {"$set": update_data}
            )
            
            # NOTE: Refund logic is now replaced with payment cancellation (handled above)
            # Payment is canceled immediately when club is rejected, no refund needed
            # Old refund logic kept for reference but not used
            refund_amount = None
            # if request.status in [ClubApprovalStatus.REJECTED_PERMANENT, ClubApprovalStatus.REJECTED]:
            #     refund_amount = await self._process_club_refund(
            #         club_id, owner_doc, request.refund_amount, admin_email
            #     )
            
            # Generate approval ID for tracking
            approval_id = str(ObjectId())
            
            # Log the approval/rejection action
            await self._log_approval_action(
                club_id, admin_email, request, previous_status, 
                approval_id, ip_address, refund_amount
            )
            
            # Send email notification if requested and owner email available
            notification_sent = False
            if request.notify_owner and owner_email:
                notification_sent = await self._send_approval_notification(
                    owner_email, club_doc.get("name", "Unknown Club"), 
                    request, owner_doc.get("full_name", "Club Owner")
                )
            
            # Determine rejection flags
            rejection_type = None
            is_resubmit = None
            is_club_reject_permanently = None
            is_club_reject_temporary = None
            
            if request.status == ClubApprovalStatus.REJECTED_TEMPORARY:
                rejection_type = "temporary"
                is_resubmit = True
                is_club_reject_permanently = False
                is_club_reject_temporary = True
            elif request.status in [ClubApprovalStatus.REJECTED_PERMANENT, ClubApprovalStatus.REJECTED]:
                rejection_type = "permanent"
                is_resubmit = False
                is_club_reject_permanently = True
                is_club_reject_temporary = False
            
            return ClubApprovalResponse(
                success=True,
                message=f"Club {request.status.value} successfully",
                club_id=club_id,
                previous_status=previous_status,
                new_status=update_data["status"],  # Use actual status set in database
                notification_sent=notification_sent,
                owner_email=owner_email,
                admin_email=admin_email,
                timestamp=datetime.utcnow(),
                approval_id=approval_id,
                rejection_type=rejection_type,
                refund_amount=refund_amount,
                is_resubmit=is_resubmit,
                is_club_reject_permanently=is_club_reject_permanently,
                is_club_reject_temporary=is_club_reject_temporary
            )
            
        except Exception as e:
            print(f"Error in approve_reject_club: {e}")
            return ClubApprovalResponse(
                success=False,
                message=f"Failed to {request.status.value} club: {str(e)}",
                club_id=club_id,
                previous_status="unknown",
                new_status=request.status.value,
                notification_sent=False,
                admin_email=admin_email,
                timestamp=datetime.utcnow(),
                approval_id=""
            )

    async def _send_approval_notification(self, owner_email: str, club_name: str, 
                                        request: ClubApprovalRequest, owner_name: str) -> bool:
        """Send email notification to club owner about approval/rejection"""
        try:
            if request.status == ClubApprovalStatus.APPROVED:
                subject = f"🎉 Your Club '{club_name}' Has Been Approved!"
                body = f"""
Dear {owner_name},

Congratulations! Your club "{club_name}" has been approved and is now live on our platform.

💳 **Payment Processed:**
Your payment has been successfully charged and your club is now active.

Your club is now visible to potential members and you can start:
- Adding moderators and content
- Posting betting picks and analysis
- Growing your community
- Managing subscriptions

You can access your club management dashboard immediately.

Welcome to our community of successful club owners!

Best regards,
The Admin Team
"""
            elif request.status == ClubApprovalStatus.REJECTED_TEMPORARY:
                subject = f"🔧 Action Required: Your Club '{club_name}' Needs Updates"
                reason = request.reason or "Please review our community guidelines and resubmit."
                body = f"""
Dear {owner_name},

Thank you for your interest in creating a club on our platform.

Your club "{club_name}" requires some adjustments before we can approve it.

**Reason for temporary rejection:**
{reason}

**Next Steps:**
1. Please review the feedback above
2. Make the necessary changes to your club
3. Use our club edit feature to update your club details
4. Resubmit your club for review

You can edit your club using our club management dashboard. Once you've made the requested changes, simply resubmit your application and we'll review it again.

If you have any questions, please contact our support team.

Best regards,
The Admin Team
"""
            else:  # REJECTED_PERMANENT or REJECTED
                subject = f"Final Decision on Your Club Application: '{club_name}'"
                reason = request.reason or "Your club does not meet our community guidelines."
                
                body = f"""
Dear {owner_name},

Thank you for your interest in creating a club on our platform.

After careful review, we have decided not to approve your club "{club_name}".

**Reason:**
{reason}

💳 **Payment Information:**
Good news - since your club was not approved, your payment hold has been CANCELED and you have NOT been charged. 
The authorization hold on your card has been released immediately and the funds are now available in your account.

Unfortunately, this decision is final and you cannot resubmit this club.

We appreciate your understanding and wish you the best in your future endeavors.

If you have any questions about this decision, please contact our support team.

Best regards,
The Admin Team
"""
            
            await send_email(owner_email, subject, body)
            print(f"✅ Notification email sent to {owner_email}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to send notification email: {e}")
            return False

    async def _log_approval_action(self, club_id: str, admin_email: str, 
                                 request: ClubApprovalRequest, previous_status: str,
                                 approval_id: str, ip_address: Optional[str], refund_amount: Optional[float] = None):
        """Log approval/rejection action for audit purposes"""
        try:
            log_entry = {
                "_id": ObjectId(),
                "approval_id": approval_id,
                "club_id": club_id,
                "admin_email": admin_email,
                "action": f"CLUB_{request.status.value.upper()}",
                "previous_status": previous_status,
                "new_status": request.status.value,
                "reason": request.reason,
                "admin_notes": request.admin_notes,
                "notification_sent": request.notify_owner,
                "timestamp": datetime.utcnow(),
                "ip_address": ip_address,
                "rejection_type": request.rejection_type,
                "refund_amount": refund_amount,
                "is_resubmit": request.status == ClubApprovalStatus.REJECTED_TEMPORARY
            }
            
            await self.club_admin_logs_collection.insert_one(log_entry)
            
        except Exception as e:
            print(f"Error logging approval action: {e}")

    async def _process_club_refund(self, club_id: str, owner_doc: Optional[Dict], 
                                 manual_refund_amount: Optional[float], admin_email: str) -> Optional[float]:
        """
        Process automatic refund for permanently rejected clubs
        
        Args:
            club_id: Club ID that was permanently rejected
            owner_doc: Club owner document from users collection
            manual_refund_amount: Manual refund amount (not used in automatic mode)
            admin_email: Admin email for logging
            
        Returns:
            Total refund amount processed, or None if no refund was processed
        """
        try:
            print(f"Processing automatic refund for permanently rejected club: {club_id}")
            
            # Find all payments for this club and captain
            captain_id = owner_doc.get("_id") if owner_doc else None
            if not captain_id:
                print(f"No captain ID found for club {club_id}")
                return None
            
            # Query club_payments collection for payments related to this club
            payments_cursor = self.club_payments_collection.find({
                "club_id": club_id,
                "captain_id": str(captain_id),
                "payment_status": {"$in": ["succeeded", "requires_confirmation", "processing", "pending"]}
            })
            
            payments = await payments_cursor.to_list(None)
            print(f"Found {len(payments)} payments for club {club_id}")
            
            if not payments:
                print(f"No payments found for club {club_id}")
                return 0.0
            
            total_refunded = 0.0
            refund_details = []
            
            for payment in payments:
                payment_intent_id = payment.get("payment_intent_id")
                amount = payment.get("amount", 0)
                currency = payment.get("currency", "USD")
                payment_status = payment.get("payment_status")
                
                print(f"Processing payment: {payment_intent_id}, amount: {amount}, status: {payment_status}")
                
                try:
                    if payment_status == "requires_confirmation":
                        # Cancel the payment intent if it hasn't been confirmed yet
                        print(f"Cancelling unconfirmed payment intent: {payment_intent_id}")
                        cancelled_payment = stripe.PaymentIntent.cancel(payment_intent_id)
                        print(f"Payment intent cancelled: {cancelled_payment.status}")
                        
                        # Update payment status in database
                        await self.club_payments_collection.update_one(
                            {"payment_intent_id": payment_intent_id},
                            {
                                "$set": {
                                    "payment_status": "cancelled",
                                    "refunded_at": datetime.utcnow(),
                                    "refunded_by": admin_email,
                                    "refund_reason": "Club permanently rejected"
                                }
                            }
                        )
                        
                        total_refunded += amount
                        refund_details.append({
                            "payment_intent_id": payment_intent_id,
                            "amount": amount,
                            "currency": currency,
                            "action": "cancelled",
                            "status": "success"
                        })
                        
                    elif payment_status == "succeeded":
                        # Create a refund for confirmed payments
                        print(f"Creating refund for confirmed payment: {payment_intent_id}")
                        refund = stripe.Refund.create(
                            payment_intent=payment_intent_id,
                            reason="requested_by_customer",
                            metadata={
                                'refund_type': 'admin_payment_refund',
                                'service': 'admin',
                                'club_id': club_id,
                                'admin_id': admin_email,  # Use admin_email as ID
                                'admin_email': admin_email,
                                'reason': 'club_permanently_rejected',
                                'payment_type': 'refund'
                            }
                        )
                        print(f"Refund created: {refund.id}, status: {refund.status}")
                        
                        # Update payment status in database
                        await self.club_payments_collection.update_one(
                            {"payment_intent_id": payment_intent_id},
                            {
                                "$set": {
                                    "payment_status": "refunded",
                                    "refund_id": refund.id,
                                    "refunded_at": datetime.utcnow(),
                                    "refunded_by": admin_email,
                                    "refund_reason": "Club permanently rejected"
                                }
                            }
                        )
                        
                        total_refunded += amount
                        refund_details.append({
                            "payment_intent_id": payment_intent_id,
                            "amount": amount,
                            "currency": currency,
                            "refund_id": refund.id,
                            "action": "refunded",
                            "status": refund.status
                        })
                        
                    else:
                        print(f"Skipping payment {payment_intent_id} with status: {payment_status}")
                        
                except stripe.error.StripeError as stripe_error:
                    print(f"Stripe error processing payment {payment_intent_id}: {stripe_error}")
                    refund_details.append({
                        "payment_intent_id": payment_intent_id,
                        "amount": amount,
                        "currency": currency,
                        "action": "failed",
                        "status": "error",
                        "error": str(stripe_error)
                    })
                    
                except Exception as e:
                    print(f"Error processing payment {payment_intent_id}: {e}")
                    refund_details.append({
                        "payment_intent_id": payment_intent_id,
                        "amount": amount,
                        "currency": currency,
                        "action": "failed",
                        "status": "error",
                        "error": str(e)
                    })
            
            # Log refund details
            if refund_details:
                refund_log = {
                    "club_id": club_id,
                    "captain_id": str(captain_id),
                    "admin_email": admin_email,
                    "total_refunded": total_refunded,
                    "refund_details": refund_details,
                    "timestamp": datetime.utcnow(),
                    "reason": "Club permanently rejected"
                }
                
                # Store refund log in club_refunds collection
                try:
                    await self.club_payments_collection.insert_one({
                        "_id": ObjectId(),
                        "type": "refund_log",
                        **refund_log
                    })
                except Exception as e:
                    print(f"Error storing refund log: {e}")
            
            print(f"Refund processing completed. Total refunded: {total_refunded}")
            return total_refunded
            
        except Exception as e:
            print(f"Error in _process_club_refund: {e}")
            return None

    # ========================================
    # Club Monitoring Service
    # ========================================

    async def get_club_monitoring_data(self, club_id: str, period: ActivityPeriod = ActivityPeriod.WEEKLY) -> ClubMonitoringResponse:
        """
        Get comprehensive club monitoring data including activity metrics and health status
        
        Args:
            club_id: Club ID to monitor
            period: Time period for metrics (daily/weekly/monthly)
            
        Returns:
            ClubMonitoringResponse with complete monitoring data
        """
        try:
            print(f"DEBUG: Getting monitoring data for club {club_id} (period: {period.value})")
            
            # Validate club exists
            club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club_doc:
                return ClubMonitoringResponse(
                    success=False,
                    message="Club not found",
                    club_id=club_id,
                    club_name="Unknown",
                    captain_name="Unknown",
                    captain_email="Unknown",
                    activity_metrics=ClubActivityMetrics(
                        period=period,
                        date_range={"start_date": "", "end_date": ""},
                        messages_sent=0,
                        picks_posted=0,
                        new_members=0,
                        active_members=0,
                        engagement_rate=0.0,
                        avg_daily_messages=0.0,
                        avg_daily_picks=0.0,
                        days_since_last_activity=0,
                        is_inactive=True
                    ),
                    performance_summary=ClubPerformanceSummary(
                        total_picks=0,
                        winning_picks=0,
                        losing_picks=0,
                        pending_picks=0,
                        win_rate=0.0,
                        loss_rate=0.0,
                        roi=0.0,
                        profit_loss=0.0,
                        best_streak=0,
                        current_streak=0,
                        performance_trend="stable"
                    ),
                    health_status=ClubHealthStatus(
                        overall_health="poor",
                        health_score=0,
                        issues=["Club not found"],
                        recommendations=[],
                        flags={}
                    ),
                    last_updated="",
                    monitoring_id=""
                )
            
            # Get club and captain details
            club_name = club_doc.get("name", "Unknown Club")
            captain_id = club_doc.get("captain_id")
            captain_name = "Unknown Captain"
            captain_email = "Unknown"
            
            if captain_id:
                captain_doc = await self.users_collection.find_one({"_id": ObjectId(captain_id)})
                if captain_doc:
                    captain_name = captain_doc.get("full_name", "Unknown Captain")
                    captain_email = captain_doc.get("email", "Unknown")
            
            # Calculate date range based on period
            end_date = datetime.utcnow()
            if period == ActivityPeriod.DAILY:
                start_date = end_date - timedelta(days=1)
            elif period == ActivityPeriod.WEEKLY:
                start_date = end_date - timedelta(days=7)
            else:  # MONTHLY
                start_date = end_date - timedelta(days=30)
            
            # Get activity metrics
            activity_metrics = await self._get_activity_metrics(club_id, period, start_date, end_date)
            
            # Get performance summary
            performance_summary = await self._get_performance_summary(club_id)
            
            # Calculate health status
            health_status = await self._calculate_health_status(
                club_id, activity_metrics, performance_summary
            )
            
            monitoring_id = str(ObjectId())
            
            return ClubMonitoringResponse(
                success=True,
                message=f"Club monitoring data retrieved successfully for {period.value} period",
                club_id=club_id,
                club_name=club_name,
                captain_name=captain_name,
                captain_email=captain_email,
                activity_metrics=activity_metrics,
                performance_summary=performance_summary,
                health_status=health_status,
                last_updated=datetime.utcnow().strftime("%d %b %Y %H:%M"),
                monitoring_id=monitoring_id
            )
            
        except Exception as e:
            print(f"Error in get_club_monitoring_data: {e}")
            return ClubMonitoringResponse(
                success=False,
                message=f"Failed to retrieve monitoring data: {str(e)}",
                club_id=club_id,
                club_name="Unknown",
                captain_name="Unknown",
                captain_email="Unknown",
                activity_metrics=ClubActivityMetrics(
                    period=period,
                    date_range={"start_date": "", "end_date": ""},
                    messages_sent=0,
                    picks_posted=0,
                    new_members=0,
                    active_members=0,
                    engagement_rate=0.0,
                    avg_daily_messages=0.0,
                    avg_daily_picks=0.0,
                    days_since_last_activity=0,
                    is_inactive=True
                ),
                performance_summary=ClubPerformanceSummary(
                    total_picks=0,
                    winning_picks=0,
                    losing_picks=0,
                    pending_picks=0,
                    win_rate=0.0,
                    loss_rate=0.0,
                    roi=0.0,
                    profit_loss=0.0,
                    best_streak=0,
                    current_streak=0,
                    performance_trend="stable"
                ),
                health_status=ClubHealthStatus(
                    overall_health="poor",
                    health_score=0,
                    issues=["Failed to retrieve data"],
                    recommendations=[],
                    flags={}
                ),
                last_updated="",
                monitoring_id=""
            )

    async def _get_activity_metrics(self, club_id: str, period: ActivityPeriod, 
                                  start_date: datetime, end_date: datetime) -> ClubActivityMetrics:
        """Get club activity metrics for the specified period"""
        try:
            # Query activity data from club_activity_collection
            activity_filter = {
                "club_id": club_id,
                "timestamp": {"$gte": start_date, "$lte": end_date}
            }
            
            # Count messages and picks
            messages_sent = 0
            picks_posted = 0
            
            async for activity in self.club_activity_collection.find(activity_filter):
                activity_type = activity.get("type", "")
                if activity_type == "message":
                    messages_sent += 1
                elif activity_type == "pick":
                    picks_posted += 1
            
            # Get membership data for the period
            membership_filter = {
                "club_id": club_id,
                "joined_date": {"$gte": start_date, "$lte": end_date}
            }
            new_members = await self.club_memberships_collection.count_documents(membership_filter)
            
            # Get active members (had activity in period)
            active_members_cursor = self.club_activity_collection.distinct(
                "user_id", 
                {"club_id": club_id, "timestamp": {"$gte": start_date, "$lte": end_date}}
            )
            active_members = len(await active_members_cursor)
            
            # Calculate engagement rate
            total_members = await self.club_memberships_collection.count_documents({
                "club_id": club_id, 
                "is_active": True
            })
            engagement_rate = (active_members / total_members * 100) if total_members > 0 else 0.0
            
            # Calculate averages
            days_in_period = (end_date - start_date).days or 1
            avg_daily_messages = messages_sent / days_in_period
            avg_daily_picks = picks_posted / days_in_period
            
            # Get last activity date
            last_activity_doc = await self.club_activity_collection.find_one(
                {"club_id": club_id},
                sort=[("timestamp", -1)]
            )
            
            last_activity_date = None
            days_since_last_activity = 0
            
            if last_activity_doc:
                last_activity_timestamp = last_activity_doc.get("timestamp")
                if last_activity_timestamp:
                    last_activity_date = last_activity_timestamp.strftime("%d %b %Y")
                    days_since_last_activity = (datetime.utcnow() - last_activity_timestamp).days
                    
            is_inactive = days_since_last_activity > 7
            
            return ClubActivityMetrics(
                period=period,
                date_range={
                    "start_date": start_date.strftime("%d %b %Y"),
                    "end_date": end_date.strftime("%d %b %Y")
                },
                messages_sent=messages_sent,
                picks_posted=picks_posted,
                new_members=new_members,
                active_members=active_members,
                engagement_rate=round(engagement_rate, 2),
                avg_daily_messages=round(avg_daily_messages, 2),
                avg_daily_picks=round(avg_daily_picks, 2),
                last_activity_date=last_activity_date,
                days_since_last_activity=days_since_last_activity,
                is_inactive=is_inactive
            )
            
        except Exception as e:
            print(f"Error getting activity metrics: {e}")
            return ClubActivityMetrics(
                period=period,
                date_range={"start_date": "", "end_date": ""},
                messages_sent=0,
                picks_posted=0,
                new_members=0,
                active_members=0,
                engagement_rate=0.0,
                avg_daily_messages=0.0,
                avg_daily_picks=0.0,
                days_since_last_activity=0,
                is_inactive=True
            )

    async def _get_performance_summary(self, club_id: str) -> ClubPerformanceSummary:
        """Get club performance summary from picks data"""
        try:
            # Get all picks for the club
            picks_cursor = self.club_picks_collection.find({"club_id": club_id})
            
            total_picks = 0
            winning_picks = 0
            losing_picks = 0
            pending_picks = 0
            total_profit_loss = 0.0
            current_streak = 0
            best_streak = 0
            temp_streak = 0
            
            last_outcome = None
            
            async for pick in picks_cursor:
                total_picks += 1
                outcome = pick.get("outcome", "pending")
                profit_loss = pick.get("profit_loss", 0.0)
                
                if outcome == "won":
                    winning_picks += 1
                    total_profit_loss += profit_loss
                    
                    # Calculate streaks
                    if last_outcome == "won":
                        temp_streak += 1
                    else:
                        temp_streak = 1
                    current_streak = temp_streak
                    best_streak = max(best_streak, temp_streak)
                    
                elif outcome == "lost":
                    losing_picks += 1
                    total_profit_loss += profit_loss  # Should be negative
                    temp_streak = 0
                    current_streak = 0
                    
                else:
                    pending_picks += 1
                
                last_outcome = outcome
            
            # Calculate rates
            win_rate = (winning_picks / total_picks * 100) if total_picks > 0 else 0.0
            loss_rate = (losing_picks / total_picks * 100) if total_picks > 0 else 0.0
            
            # Calculate ROI (simplified calculation)
            roi = total_profit_loss  # Assuming profit_loss includes ROI calculation
            
            # Determine performance trend (simplified)
            if win_rate > 60:
                performance_trend = "improving"
            elif win_rate < 40:
                performance_trend = "declining"
            else:
                performance_trend = "stable"
            
            return ClubPerformanceSummary(
                total_picks=total_picks,
                winning_picks=winning_picks,
                losing_picks=losing_picks,
                pending_picks=pending_picks,
                win_rate=round(win_rate, 2),
                loss_rate=round(loss_rate, 2),
                roi=round(roi, 2),
                profit_loss=round(total_profit_loss, 2),
                best_streak=best_streak,
                current_streak=current_streak,
                performance_trend=performance_trend
            )
            
        except Exception as e:
            print(f"Error getting performance summary: {e}")
            return ClubPerformanceSummary(
                total_picks=0,
                winning_picks=0,
                losing_picks=0,
                pending_picks=0,
                win_rate=0.0,
                loss_rate=0.0,
                roi=0.0,
                profit_loss=0.0,
                best_streak=0,
                current_streak=0,
                performance_trend="stable"
            )

    async def _calculate_health_status(self, club_id: str, activity_metrics: ClubActivityMetrics, 
                                     performance_summary: ClubPerformanceSummary) -> ClubHealthStatus:
        """Calculate club health status based on activity and performance"""
        try:
            health_score = 100
            issues = []
            recommendations = []
            flags = {}
            
            # Check activity issues
            if activity_metrics.is_inactive:
                health_score -= 30
                issues.append("No activity in the last 7 days")
                recommendations.append("Encourage club owner to post content and engage members")
                flags["inactive"] = True
            
            if activity_metrics.engagement_rate < 20:
                health_score -= 20
                issues.append("Low member engagement rate")
                recommendations.append("Review content quality and member value proposition")
                flags["low_engagement"] = True
            
            if activity_metrics.picks_posted == 0:
                health_score -= 15
                issues.append("No betting picks posted recently")
                recommendations.append("Remind club owner to share betting analysis and picks")
                flags["no_picks"] = True
            
            # Check performance issues
            if performance_summary.win_rate < 40 and performance_summary.total_picks > 10:
                health_score -= 25
                issues.append("Poor pick performance (win rate below 40%)")
                recommendations.append("Consider providing guidance on pick quality and analysis")
                flags["poor_performance"] = True
            
            if performance_summary.total_picks == 0:
                health_score -= 20
                issues.append("No betting picks recorded")
                recommendations.append("Encourage club to start posting picks with proper tracking")
                flags["no_pick_history"] = True
            
            # Determine overall health
            if health_score >= 80:
                overall_health = "excellent"
            elif health_score >= 60:
                overall_health = "good"
            elif health_score >= 40:
                overall_health = "fair"
            else:
                overall_health = "poor"
            
            # Add positive recommendations if club is doing well
            if not issues:
                recommendations.append("Club is performing well, continue current strategies")
                recommendations.append("Consider expanding content and member engagement")
            
            return ClubHealthStatus(
                overall_health=overall_health,
                health_score=max(0, health_score),
                issues=issues,
                recommendations=recommendations,
                flags=flags
            )
            
        except Exception as e:
            print(f"Error calculating health status: {e}")
            return ClubHealthStatus(
                overall_health="poor",
                health_score=0,
                issues=["Error calculating health status"],
                recommendations=[],
                flags={}
            )

    # ========================================
    # Club Picks Service
    # ========================================

    async def get_club_picks(self, club_id: str, request: ClubPicksRequest) -> ClubPicksResponse:
        """
        Get club picks with filtering, search, and pagination
        
        Args:
            club_id: Club ID to get picks for
            request: ClubPicksRequest with filters and pagination
            
        Returns:
            ClubPicksResponse with picks data and summary
        """
        start_time = time.time()
        
        try:
            print(f"DEBUG: Getting picks for club {club_id} with filters: {request.dict()}")
            
            # Validate club exists
            club_doc = await self.clubs_collection.find_one({"_id": ObjectId(club_id)})
            if not club_doc:
                return self._empty_picks_response(club_id, "Club not found", request)
            
            club_name = club_doc.get("name", "Unknown Club")
            
            # Build picks query
            picks_filter = await self._build_picks_filter(club_id, request)
            
            # Get total count for pagination
            total_picks = await self.club_picks_collection.count_documents(picks_filter)
            
            # Calculate pagination
            total_pages = (total_picks + request.limit - 1) // request.limit
            skip = (request.page - 1) * request.limit
            
            # Build sort criteria
            sort_criteria = self._build_picks_sort_criteria(request.sort_by, request.sort_order)
            
            # Get picks data
            picks_cursor = self.club_picks_collection.find(picks_filter).sort(sort_criteria).skip(skip).limit(request.limit)
            picks_data = []
            
            async for pick_doc in picks_cursor:
                pick_item = await self._format_pick_item(pick_doc)
                picks_data.append(pick_item)
            
            # Get summary statistics
            summary = await self._get_picks_summary(club_id, picks_filter)
            
            # Create pagination metadata
            pagination = ClubPicksPagination(
                current_page=request.page,
                total_pages=total_pages,
                total_records=total_picks,
                records_per_page=request.limit,
                has_next=request.page < total_pages,
                has_previous=request.page > 1
            )
            
            end_time = time.time()
            response_time = round((end_time - start_time) * 1000, 2)
            
            return ClubPicksResponse(
                success=True,
                message=f"Retrieved {len(picks_data)} picks successfully",
                club_id=club_id,
                club_name=club_name,
                data=picks_data,
                pagination=pagination,
                summary=summary,
                filters_applied=self._get_applied_picks_filters(request),
                response_time_ms=response_time
            )
            
        except Exception as e:
            print(f"Error in get_club_picks: {e}")
            return self._empty_picks_response(club_id, f"Failed to retrieve picks: {str(e)}", request)

    async def _build_picks_filter(self, club_id: str, request: ClubPicksRequest) -> Dict[str, Any]:
        """Build MongoDB filter for picks query"""
        picks_filter = {"club_id": club_id}
        
        # Status filter
        if request.status:
            picks_filter["status"] = request.status.value
        
        # Pick type filter
        if request.pick_type:
            picks_filter["pick_type"] = request.pick_type.value
        
        # Submitted by role filter
        if request.submitted_by_role:
            picks_filter["submitted_by_role"] = request.submitted_by_role.value
        
        # Sport filter
        if request.sport:
            picks_filter["sport"] = {"$regex": request.sport, "$options": "i"}
        
        # Date range filter
        if request.date_from or request.date_to:
            date_filter = {}
            if request.date_from:
                try:
                    date_from = datetime.strptime(request.date_from, "%Y-%m-%d")
                    date_filter["$gte"] = date_from
                except ValueError:
                    pass
            
            if request.date_to:
                try:
                    date_to = datetime.strptime(request.date_to, "%Y-%m-%d") + timedelta(days=1)
                    date_filter["$lt"] = date_to
                except ValueError:
                    pass
            
            if date_filter:
                picks_filter["date_submitted"] = date_filter
        
        # Search filter
        if request.search:
            search_regex = {"$regex": request.search, "$options": "i"}
            picks_filter["$or"] = [
                {"title": search_regex},
                {"description": search_regex}
            ]
        
        return picks_filter

    def _build_picks_sort_criteria(self, sort_by: str, sort_order: SortOrder) -> List[tuple]:
        """Build sort criteria for picks query"""
        sort_direction = 1 if sort_order == SortOrder.ASC else -1
        
        valid_sort_fields = {
            "date_submitted": "date_submitted",
            "title": "title",
            "status": "status",
            "odds": "odds",
            "profit_loss": "profit_loss"
        }
        
        sort_field = valid_sort_fields.get(sort_by, "date_submitted")
        return [(sort_field, sort_direction)]

    async def _format_pick_item(self, pick_doc: Dict[str, Any]) -> ClubPickItem:
        """Format raw pick document into ClubPickItem"""
        try:
            # Get submitter details
            submitted_by = "Unknown"
            submitted_by_email = None
            submitted_by_role = SubmittedByRole.CAPTAIN
            
            submitter_id = pick_doc.get("submitted_by_id")
            if submitter_id:
                submitter_doc = await self.users_collection.find_one({"_id": ObjectId(submitter_id)})
                if submitter_doc:
                    submitted_by = submitter_doc.get("full_name", "Unknown")
                    submitted_by_email = submitter_doc.get("email")
                    
                    # Get role from membership
                    membership_doc = await self.club_memberships_collection.find_one({
                        "club_id": pick_doc.get("club_id"),
                        "user_id": str(submitter_id)
                    })
                    if membership_doc:
                        role = membership_doc.get("role", "captain")
                        if role in ["captain", "moderator", "analyst", "editor"]:
                            submitted_by_role = SubmittedByRole(role)
            
            return ClubPickItem(
                pick_id=str(pick_doc.get("_id")),
                title=pick_doc.get("title", "Untitled Pick"),
                description=pick_doc.get("description"),
                pick_type=PickType(pick_doc.get("pick_type", "single")),
                sport=pick_doc.get("sport"),
                odds=pick_doc.get("odds"),
                stake=pick_doc.get("stake"),
                potential_payout=pick_doc.get("potential_payout"),
                submitted_by=submitted_by,
                submitted_by_role=submitted_by_role,
                submitted_by_email=submitted_by_email,
                date_submitted=self._format_datetime(pick_doc.get("date_submitted")),
                game_date=self._format_datetime(pick_doc.get("game_date")),
                status=PickStatus(pick_doc.get("status", "pending")),
                outcome_date=self._format_datetime(pick_doc.get("outcome_date")),
                profit_loss=pick_doc.get("profit_loss"),
                tags=pick_doc.get("tags", []),
                confidence_level=pick_doc.get("confidence_level")
            )
            
        except Exception as e:
            print(f"Error formatting pick item: {e}")
            return ClubPickItem(
                pick_id=str(pick_doc.get("_id", ObjectId())),
                title="Error Loading Pick",
                pick_type=PickType.SINGLE,
                submitted_by="Unknown",
                submitted_by_role=SubmittedByRole.CAPTAIN,
                date_submitted="Unknown",
                status=PickStatus.PENDING
            )

    async def _get_picks_summary(self, club_id: str, picks_filter: Dict[str, Any]) -> ClubPicksSummary:
        """Get summary statistics for picks"""
        try:
            # Count picks by status
            total_picks = await self.club_picks_collection.count_documents(picks_filter)
            
            status_counts = {}
            for status in ["pending", "won", "lost", "cancelled", "void"]:
                status_filter = picks_filter.copy()
                status_filter["status"] = status
                count = await self.club_picks_collection.count_documents(status_filter)
                status_counts[status] = count
            
            # Calculate win rate
            total_completed = status_counts["won"] + status_counts["lost"]
            win_rate = (status_counts["won"] / total_completed * 100) if total_completed > 0 else 0.0
            
            # Calculate total profit/loss
            profit_loss_pipeline = [
                {"$match": picks_filter},
                {"$group": {
                    "_id": None,
                    "total_profit_loss": {"$sum": "$profit_loss"},
                    "avg_odds": {"$avg": "$odds"}
                }}
            ]
            
            profit_result = await self.club_picks_collection.aggregate(profit_loss_pipeline).to_list(1)
            total_profit_loss = profit_result[0]["total_profit_loss"] if profit_result else 0.0
            avg_odds = profit_result[0]["avg_odds"] if profit_result else None
            
            # Get most active contributor
            contributor_pipeline = [
                {"$match": picks_filter},
                {"$group": {
                    "_id": "$submitted_by_id",
                    "pick_count": {"$sum": 1}
                }},
                {"$sort": {"pick_count": -1}},
                {"$limit": 1}
            ]
            
            contributor_result = await self.club_picks_collection.aggregate(contributor_pipeline).to_list(1)
            most_active_contributor = None
            
            if contributor_result:
                contributor_id = contributor_result[0]["_id"]
                if contributor_id:
                    contributor_doc = await self.users_collection.find_one({"_id": ObjectId(contributor_id)})
                    if contributor_doc:
                        most_active_contributor = contributor_doc.get("full_name", "Unknown")
            
            return ClubPicksSummary(
                total_picks=total_picks,
                pending_picks=status_counts["pending"],
                won_picks=status_counts["won"],
                lost_picks=status_counts["lost"],
                cancelled_picks=status_counts["cancelled"],
                void_picks=status_counts["void"],
                win_rate=round(win_rate, 2),
                total_profit_loss=round(total_profit_loss, 2),
                avg_odds=round(avg_odds, 2) if avg_odds else None,
                most_active_contributor=most_active_contributor
            )
            
        except Exception as e:
            print(f"Error getting picks summary: {e}")
            return ClubPicksSummary(
                total_picks=0,
                pending_picks=0,
                won_picks=0,
                lost_picks=0,
                cancelled_picks=0,
                void_picks=0,
                win_rate=0.0,
                total_profit_loss=0.0
            )

    def _format_datetime(self, dt) -> Optional[str]:
        """Format datetime to DD MMM YYYY HH:MM format"""
        if not dt:
            return None
        
        try:
            if isinstance(dt, datetime):
                return dt.strftime("%d %b %Y %H:%M")
            return None
        except:
            return None

    def _get_applied_picks_filters(self, request: ClubPicksRequest) -> Dict[str, Any]:
        """Get dictionary of applied filters for response"""
        filters = {}
        
        if request.status:
            filters["status"] = request.status.value
        if request.pick_type:
            filters["pick_type"] = request.pick_type.value
        if request.submitted_by_role:
            filters["submitted_by_role"] = request.submitted_by_role.value
        if request.sport:
            filters["sport"] = request.sport
        if request.date_from:
            filters["date_from"] = request.date_from
        if request.date_to:
            filters["date_to"] = request.date_to
        if request.search:
            filters["search"] = request.search
        
        filters["page"] = request.page
        filters["limit"] = request.limit
        filters["sort_by"] = request.sort_by
        filters["sort_order"] = request.sort_order.value
        
        return filters

    def _empty_picks_response(self, club_id: str, message: str, request: ClubPicksRequest) -> ClubPicksResponse:
        """Create empty picks response for error cases"""
        return ClubPicksResponse(
            success=False,
            message=message,
            club_id=club_id,
            club_name="Unknown",
            data=[],
            pagination=ClubPicksPagination(
                current_page=request.page,
                total_pages=0,
                total_records=0,
                records_per_page=request.limit,
                has_next=False,
                has_previous=False
            ),
            summary=ClubPicksSummary(
                total_picks=0,
                pending_picks=0,
                won_picks=0,
                lost_picks=0,
                cancelled_picks=0,
                void_picks=0,
                win_rate=0.0,
                total_profit_loss=0.0
            ),
            filters_applied={}
        )

# Global service instance
admin_club_management_service = AdminClubManagementService()