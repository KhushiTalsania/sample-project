"""
Support & Feedback Service

This service handles support and feedback submissions, stores them in the database,
and sends email notifications.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from bson import ObjectId

from core.database.collections import get_collections
from core.utils.response_utils import create_response
from core.utils.email_service import get_email_service

logger = logging.getLogger(__name__)

class SupportFeedbackService:
    """Service for managing support and feedback submissions"""
    
    def __init__(self):
        self._collections = None
        self._support_feedback_collection = None
    
    def _ensure_collections_initialized(self):
        """Lazy initialization of collections to prevent circular imports"""
        if self._collections is None:
            self._collections = get_collections()
            self._support_feedback_collection = self._collections.get_support_feedback_collection()
    
    async def submit_support_feedback(
        self, 
        first_name: str,
        email: str,
        subject: str,
        message: str,
        type: str,
        selected_club: Optional[str] = None,
        attachment_filename: Optional[str] = None,
        attachment_path: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Submit support and feedback with email notification
        
        Args:
            first_name: User's first name
            email: User's email address
            subject: Brief description of the inquiry
            message: Detailed message
            type: Type of support request ('club' or 'platform')
            selected_club: Club name_based_id if type is 'club' (optional)
            attachment_filename: Name of uploaded file (optional)
            attachment_path: Path to uploaded file (optional)
        
        Returns:
            Tuple of (success, data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            
            # Validate email format
            if not self._is_valid_email(email):
                return False, None, "Invalid email format"
            
            # Create support feedback record
            support_record = {
                "first_name": first_name.strip(),
                "email": email.strip().lower(),
                "subject": subject.strip(),
                "message": message.strip(),
                "type": type.strip().lower(),
                "selected_club": selected_club.strip() if selected_club else None,
                "attachment_filename": attachment_filename,
                "attachment_path": attachment_path,
                "status": "new",  # new, in_progress, resolved, closed
                "response_status": "pending",  # pending, in_progress, resolved, closed (stored in lowercase)
                "priority": "medium",  # low, medium, high, urgent
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "ip_address": None,  # Could be added from request context
                "user_agent": None,  # Could be added from request context
            }
            
            # Insert into database
            result = await self._support_feedback_collection.insert_one(support_record)
            support_id = str(result.inserted_id)
            
            logger.info(f"Support feedback submitted successfully with ID: {support_id}")
            
            # Send email notification
            email_sent = await self._send_support_email(
                support_id, first_name, email, subject, message, type, selected_club, attachment_filename
            )
            
            # Prepare response data
            response_data = {
                "support_id": support_id,
                "first_name": first_name,
                "email": email,
                "subject": subject,
                "type": type,
                "selected_club": selected_club,
                "status": "new",
                "response_status": "pending",  # Default response status
                "created_at": support_record["created_at"].isoformat(),
                    "attachment_path": attachment_path,  # Include attachment URL in response
                "email_sent": email_sent
            }
            
            return True, response_data, None
            
        except Exception as e:
            logger.error(f"Error submitting support feedback: {e}")
            return False, None, f"Failed to submit support feedback: {str(e)}"
    
    def _is_valid_email(self, email: str) -> bool:
        """Basic email validation"""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    async def _send_support_email(
        self, 
        support_id: str,
        first_name: str,
        email: str,
        subject: str,
        message: str,
        type: str,
        selected_club: Optional[str] = None,
        attachment_filename: Optional[str] = None
    ) -> bool:
        """Send email notification for support feedback"""
        try:
            email_service = get_email_service()
            email_sent = False
            
            if type == "club":
                # Send email to club captain and moderators
                email_sent = await self._send_club_support_email(
                    support_id, first_name, email, subject, message, selected_club, attachment_filename
                )
            else:
                # Send email to platform admins
                email_sent = await self._send_platform_support_email(
                    support_id, first_name, email, subject, message, attachment_filename
                )
            
            if email_sent:
                logger.info(f"Support email sent successfully for ID: {support_id}")
            else:
                logger.error(f"Failed to send support email for ID: {support_id}")
            
            # Send confirmation email to user
            await self._send_user_confirmation_email(
                support_id, first_name, email, subject, message, type, attachment_filename
            )
            
            return email_sent
            
        except Exception as e:
            logger.error(f"Error sending support emails: {e}")
            return False
    
    async def _send_club_support_email(
        self, 
        support_id: str,
        first_name: str,
        email: str,
        subject: str,
        message: str,
        selected_club: str,
        attachment_filename: Optional[str] = None
    ) -> bool:
        """Send email to club captain and moderators"""
        try:
            # Get club information by name_based_id
            club_collection = self._collections.get_clubs_collection()
            club = await club_collection.find_one({"name_based_id": selected_club})
            
            if not club:
                logger.error(f"Club not found with name_based_id: {selected_club}")
                return False
            
            # Get club captain email
            user_collection = self._collections.get_users_collection()
            captain = await user_collection.find_one({"_id": ObjectId(club["captain_id"])})
            
            if not captain:
                logger.error(f"Club captain not found for club: {selected_club}")
                return False
            
            # Get club moderators from detailed_moderators field
            detailed_moderators = club.get("detailed_moderators", [])
            moderator_user_ids = [mod.get("user_id") for mod in detailed_moderators if mod.get("user_id")]
            
            logger.info(f"Found {len(detailed_moderators)} detailed moderators, {len(moderator_user_ids)} with valid user_ids")
            
            if moderator_user_ids:
                moderators = await user_collection.find({
                    "_id": {"$in": [ObjectId(user_id) for user_id in moderator_user_ids]}
                }).to_list(None)
                logger.info(f"Successfully retrieved {len(moderators)} moderator user records")
            else:
                moderators = []
                logger.info("No valid moderator user_ids found")
            
            # Prepare email content
            email_subject = f"Club Support Request: {subject} - {club['name']}"
            
            # Prepare moderator info for email
            moderator_info = ""
            if detailed_moderators:
                active_moderators = [mod for mod in detailed_moderators if mod.get("status") == "active"]
                moderator_info = f"\nActive Moderators: {len(active_moderators)}"
                if active_moderators:
                    moderator_names = [mod.get("full_name", "Unknown") for mod in active_moderators]
                    moderator_info += f" ({', '.join(moderator_names)})"
            
            # Prepare attachment info
            attachment_info = ""
            if attachment_filename:
                # Construct attachment URL (adjust base URL as needed)
                base_url = "http://localhost:8959"
                attachment_url = f"{base_url}/uploads/support_attachments/{attachment_filename}"
                attachment_info = f"\n\nAttachment: {attachment_url}"
            
            email_body = f"""A new support request has been submitted for your club:

Club: {club['name']}
Support ID: {support_id}
Name: {first_name}
Email: {email}
Subject: {subject}{moderator_info}

Message:
{message}{attachment_info}
---
This message was automatically generated from the support form."""
            
            email_service = get_email_service()
            
            # Collect all recipient emails
            all_recipients = [captain["email"]]
            moderator_emails = [moderator["email"] for moderator in moderators]
            all_recipients.extend(moderator_emails)
            
            logger.info(f"Sending club support email to {len(all_recipients)} recipients: captain + {len(moderator_emails)} moderators")
            
            # Send email to captain with moderators as CC
            email_sent = await email_service.send_email(
                to_email=captain["email"],
                subject=email_subject,
                body=email_body,
                cc=moderator_emails if moderator_emails else None
            )
            
            if email_sent:
                logger.info(f"Club support email sent to captain: {captain['email']}")
                if moderator_emails:
                    logger.info(f"Club support email CC'd to moderators: {', '.join(moderator_emails)}")
                return True
            else:
                logger.error(f"Failed to send club support email to: {', '.join(all_recipients)}")
                return False
            
        except Exception as e:
            logger.error(f"Error sending club support email: {e}")
            return False
    
    async def _send_platform_support_email(
        self, 
        support_id: str,
        first_name: str,
        email: str,
        subject: str,
        message: str,
        attachment_filename: Optional[str] = None
    ) -> bool:
        """Send email to platform admins"""
        try:
            # Get admin emails from admins collection
            admins_collection = self._collections.get_admins_collection()
            admins = await admins_collection.find({}).to_list(None)
            
            logger.info(f"Found {len(admins)} admin(s) in admins collection")
            
            if not admins:
                logger.warning("No admin users found")
                return False
            
            # Prepare email content
            email_subject = f"Platform Support Request: {subject}"
            
            # Prepare attachment info
            attachment_info = ""
            if attachment_filename:
                # Construct attachment URL (adjust base URL as needed)
                base_url = os.getenv("simbet_website_url", "https://api.simbet.websitetestingbox.com/")
                attachment_url = f"{base_url}/uploads/support_attachments/{attachment_filename}"
                attachment_info = f"\n\nAttachment: {attachment_url}"
            
            email_body = f"""A new platform support request has been submitted:

Support ID: {support_id}
Name: {first_name}
Email: {email}
Subject: {subject}

Message:
{message}{attachment_info}
---
This message was automatically generated from the support form."""
            
            email_service = get_email_service()
            
            # Collect all admin emails
            admin_emails = [admin["email"] for admin in admins]
            logger.info(f"Sending platform support email to {len(admin_emails)} admin(s)")
            
            if len(admin_emails) == 1:
                # Single admin - send directly
                email_sent = await email_service.send_email(
                    to_email=admin_emails[0],
                    subject=email_subject,
                    body=email_body
                )
                if email_sent:
                    logger.info(f"Platform support email sent to admin: {admin_emails[0]}")
                    return True
                else:
                    logger.error(f"Failed to send platform support email to admin: {admin_emails[0]}")
                    return False
            else:
                # Multiple admins - send to first admin with others as CC
                primary_admin = admin_emails[0]
                cc_admins = admin_emails[1:] if len(admin_emails) > 1 else None
                
                email_sent = await email_service.send_email(
                    to_email=primary_admin,
                    subject=email_subject,
                    body=email_body,
                    cc=cc_admins
                )
                
                if email_sent:
                    logger.info(f"Platform support email sent to admin: {primary_admin}")
                    if cc_admins:
                        logger.info(f"Platform support email CC'd to admins: {', '.join(cc_admins)}")
                    return True
                else:
                    logger.error(f"Failed to send platform support email to admins: {', '.join(admin_emails)}")
                    return False
            
        except Exception as e:
            logger.error(f"Error sending platform support email: {e}")
            return False
    
    async def _send_user_confirmation_email(
        self,
        support_id: str,
        first_name: str,
        email: str,
        subject: str,
        message: str,
        type: str,
        attachment_filename: Optional[str] = None
    ) -> bool:
        """Send confirmation email to user"""
        try:
            email_service = get_email_service()
            
            # Prepare confirmation email content
            user_email_subject = "Support Request Received"
            
            # Prepare attachment info for user email
            attachment_section = ""
            if attachment_filename:
                base_url = os.getenv("ADMIN_BASE_URL", "http://localhost:8000")
                attachment_url = f"{base_url}/uploads/support_attachments/{attachment_filename}"
                attachment_section = f"""
                            <!-- Attachment Section -->
                            <div style="background-color: #fff; padding: 20px; border-radius: 8px; margin: 20px 0; border: 1px solid #e0e0e0;">
                                <h3 style="margin-top: 0; color: #333;">📎 Attachment:</h3>
                                <div style="background-color: #f5f5f5; padding: 15px; border-radius: 4px;">
                                    <a href="{attachment_url}" style="color: #4CAF50; text-decoration: none; font-weight: bold;">{attachment_filename}</a>
                                </div>
                            </div>
                """
            
            if type == "club":
                user_email_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 20px;">
                    <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                        <!-- Header -->
                        <div style="background-color: #4CAF50; color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
                            <h1 style="margin: 0; font-size: 24px;">🎯 Support Request Received</h1>
                        </div>
                        
                        <!-- Content -->
                        <div style="padding: 30px;">
                            <h2 style="color: #4CAF50; margin-top: 0;">Dear {first_name},</h2>
                            
                            <p>Thank you for contacting us regarding a club issue! We have received your support request and the club management team will get back to you as soon as possible.</p>
                            
                            <!-- Support Details Card -->
                            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4CAF50;">
                                <h3 style="margin-top: 0; color: #4CAF50;">Support Request Details</h3>
                                <p><strong>Support ID:</strong> <span style="color: #666; font-family: monospace;">{support_id}</span></p>
                                <p><strong>Subject:</strong> {subject}</p>
                            </div>
                            
                            <!-- Message Content -->
                            <div style="background-color: #fff; padding: 20px; border-radius: 8px; margin: 20px 0; border: 1px solid #e0e0e0;">
                                <h3 style="margin-top: 0; color: #333;">Your Message:</h3>
                                <div style="background-color: #f5f5f5; padding: 15px; border-radius: 4px; font-style: italic;">
                                    {message}
                                </div>
                            </div>
                            {attachment_section}
                            
                            <p style="text-align: center; margin-top: 30px; font-size: 16px;">
                                <strong>We will get back to you soon!</strong>
                            </p>
                        </div>
                        
                        <!-- Footer -->
                        <div style="background-color: #f8f9fa; padding: 20px; text-align: center; border-radius: 0 0 8px 8px; border-top: 1px solid #e0e0e0;">
                            <p style="margin: 0; color: #666;">
                                Best regards,<br>
                                <strong style="color: #4CAF50;">Support Team</strong><br>
                                <small>MVP Sports</small>
                            </p>
                        </div>
                    </div>
                </body>
                </html>
                """
            else:
                user_email_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 20px;">
                    <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                        <!-- Header -->
                        <div style="background-color: #4CAF50; color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
                            <h1 style="margin: 0; font-size: 24px;">🎯 Support Request Received</h1>
                        </div>
                        
                        <!-- Content -->
                        <div style="padding: 30px;">
                            <h2 style="color: #4CAF50; margin-top: 0;">Dear {first_name},</h2>
                            
                            <p>Thank you for contacting us regarding a club issue! We have received your support request and the club management team will get back to you as soon as possible.</p>
                            
                            <!-- Support Details Card -->
                            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4CAF50;">
                                <h3 style="margin-top: 0; color: #4CAF50;">Support Request Details</h3>
                                <p><strong>Support ID:</strong> <span style="color: #666; font-family: monospace;">{support_id}</span></p>
                                <p><strong>Subject:</strong> {subject}</p>
                            </div>
                            
                            <!-- Message Content -->
                            <div style="background-color: #fff; padding: 20px; border-radius: 8px; margin: 20px 0; border: 1px solid #e0e0e0;">
                                <h3 style="margin-top: 0; color: #333;">Your Message:</h3>
                                <div style="background-color: #f5f5f5; padding: 15px; border-radius: 4px; font-style: italic;">
                                    {message}
                                </div>
                            </div>
                            {attachment_section}
                            
                            <p style="text-align: center; margin-top: 30px; font-size: 16px;">
                                <strong>We will get back to you soon!</strong>
                            </p>
                        </div>
                        
                        <!-- Footer -->
                        <div style="background-color: #f8f9fa; padding: 20px; text-align: center; border-radius: 0 0 8px 8px; border-top: 1px solid #e0e0e0;">
                            <p style="margin: 0; color: #666;">
                                Best regards,<br>
                                <strong style="color: #4CAF50;">Support Team</strong><br>
                                <small>MVP Sports</small>
                            </p>
                        </div>
                    </div>
                </body>
                </html>
                """
            
            # Send confirmation email to user
            user_email_sent = await email_service.send_email(
                to_email=email,
                subject=user_email_subject,
                body=user_email_body,
                is_html=True
            )
            
            if user_email_sent:
                logger.info(f"Confirmation email sent to user: {email}")
            else:
                logger.error(f"Failed to send confirmation email to user: {email}")
            
            return user_email_sent
            
        except Exception as e:
            logger.error(f"Error sending user confirmation email: {e}")
            return False
    
    async def respond_to_support_feedback(
        self,
        support_id: str,
        reply_message: str,
        responded_by: str,
        responded_by_type: str,  # "admin" or "captain"
        attachment_filename: Optional[str] = None,
        attachment_path: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Respond to a support feedback ticket
        
        Args:
            support_id: Support feedback ID
            reply_message: Response message from admin/captain
            responded_by: ID or email of the person responding
            responded_by_type: Type of responder ("admin" or "captain")
            attachment_filename: Name of uploaded file (optional)
            attachment_path: Path to uploaded file (optional)
        
        Returns:
            Tuple of (success, data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            
            # Validate support ID
            if not ObjectId.is_valid(support_id):
                return False, None, "Invalid support feedback ID"
            
            # Get support feedback record
            support_record = await self._support_feedback_collection.find_one({
                "_id": ObjectId(support_id)
            })
            
            if not support_record:
                return False, None, "Support feedback not found"
            
            # Validate permissions
            feedback_type = support_record.get("type")
            selected_club = support_record.get("selected_club")
            
            if responded_by_type == "admin":
                # Admin can only respond to platform type tickets
                if feedback_type != "platform":
                    return False, None, "Admins can only respond to platform type tickets"
            elif responded_by_type == "captain":
                # Captain can only respond to club type tickets for their own clubs
                if feedback_type != "club":
                    return False, None, "Captains can only respond to club type tickets"
                # Additional validation: captain must own the club (will be checked in route)
            
            # Prepare response data
            response_data = {
                "reply_message": reply_message.strip(),
                "responded_by": responded_by,
                "responded_by_type": responded_by_type,
                "responded_at": datetime.now(timezone.utc),
                "attachment_filename": attachment_filename,
                "attachment_path": attachment_path
            }
            
            # Update support feedback record
            update_data = {
                "response_status": "completed",  # Update status from pending to completed when response is added
                "response": response_data,
                "updated_at": datetime.now(timezone.utc)
            }
            
            result = await self._support_feedback_collection.update_one(
                {"_id": ObjectId(support_id)},
                {"$set": update_data}
            )
            
            if result.modified_count == 0:
                return False, None, "Failed to update support feedback"
            
            logger.info(f"Support feedback response added for ID: {support_id}")
            
            # Send email notification to the original submitter
            email_sent = await self._send_response_email(
                support_id,
                support_record.get("first_name"),
                support_record.get("email"),
                support_record.get("subject"),
                reply_message,
                feedback_type,
                selected_club,
                attachment_filename
            )
            
            # Prepare response data
            response_result = {
                "support_id": support_id,
                "reply_message": reply_message,
                "responded_by": responded_by,
                "responded_by_type": responded_by_type,
                "response_status": "completed",
                "responded_at": response_data["responded_at"].isoformat(),
                "attachment_filename": attachment_filename,
                "attachment_path": attachment_path,  # Include attachment URL in response
                "email_sent": email_sent
            }
            
            return True, response_result, None
            
        except Exception as e:
            logger.error(f"Error responding to support feedback: {e}")
            return False, None, f"Failed to respond to support feedback: {str(e)}"
    
    async def _send_response_email(
        self,
        support_id: str,
        first_name: str,
        email: str,
        original_subject: str,
        reply_message: str,
        feedback_type: str,
        selected_club: Optional[str] = None,
        attachment_filename: Optional[str] = None
    ) -> bool:
        """Send response email to the original submitter"""
        try:
            email_service = get_email_service()
            
            # Prepare email content
            email_subject = f"Re: {original_subject} (Support ID: {support_id})"
            
            # Prepare attachment info
            attachment_section = ""
            if attachment_filename:
                base_url = os.getenv("ADMIN_BASE_URL", "http://localhost:8000")
                attachment_url = f"{base_url}/uploads/support_attachments/{attachment_filename}"
                attachment_section = f"""
                            <div style="background-color: #fff; padding: 20px; border-radius: 8px; margin: 20px 0; border: 1px solid #e0e0e0;">
                                <h3 style="margin-top: 0; color: #333;">📎 Attachment:</h3>
                                <div style="background-color: #f5f5f5; padding: 15px; border-radius: 4px;">
                                    <a href="{attachment_url}" style="color: #4CAF50; text-decoration: none; font-weight: bold;">{attachment_filename}</a>
                                </div>
                            </div>
                """
            
            email_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    <!-- Header -->
                    <div style="background-color: #4CAF50; color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
                        <h1 style="margin: 0; font-size: 24px;">📧 Response to Your Support Request</h1>
                    </div>
                    
                    <!-- Content -->
                    <div style="padding: 30px;">
                        <h2 style="color: #4CAF50; margin-top: 0;">Dear {first_name},</h2>
                        
                        <p>We have received your support request and here is our response:</p>
                        
                        <!-- Support Details Card -->
                        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4CAF50;">
                            <h3 style="margin-top: 0; color: #4CAF50;">Support Request Details</h3>
                            <p><strong>Support ID:</strong> <span style="color: #666; font-family: monospace;">{support_id}</span></p>
                            <p><strong>Subject:</strong> {original_subject}</p>
                            <p><strong>Type:</strong> {feedback_type.capitalize()}</p>
                            {f'<p><strong>Club:</strong> {selected_club}</p>' if selected_club else ''}
                        </div>
                        
                        <!-- Response Content -->
                        <div style="background-color: #fff; padding: 20px; border-radius: 8px; margin: 20px 0; border: 1px solid #e0e0e0;">
                            <h3 style="margin-top: 0; color: #333;">Response:</h3>
                            <div style="background-color: #f5f5f5; padding: 15px; border-radius: 4px; white-space: pre-wrap;">
                                {reply_message}
                            </div>
                        </div>
                        {attachment_section}
                        
                        <p style="text-align: center; margin-top: 30px; font-size: 16px;">
                            <strong>Thank you for contacting us!</strong>
                        </p>
                    </div>
                    
                    <!-- Footer -->
                    <div style="background-color: #f8f9fa; padding: 20px; text-align: center; border-radius: 0 0 8px 8px; border-top: 1px solid #e0e0e0;">
                        <p style="margin: 0; color: #666;">
                            Best regards,<br>
                            <strong style="color: #4CAF50;">Support Team</strong><br>
                            <small>MVP Sports</small>
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Send email to original submitter
            email_sent = await email_service.send_email(
                to_email=email,
                subject=email_subject,
                body=email_body,
                is_html=True
            )
            
            if email_sent:
                logger.info(f"Response email sent to original submitter: {email}")
            else:
                logger.error(f"Failed to send response email to: {email}")
            
            return email_sent
            
        except Exception as e:
            logger.error(f"Error sending response email: {e}")
            return False

# Global service instance with lazy initialization
_support_feedback_service: SupportFeedbackService = None

def get_support_feedback_service() -> SupportFeedbackService:
    """Get the global support feedback service instance"""
    global _support_feedback_service
    if _support_feedback_service is None:
        _support_feedback_service = SupportFeedbackService()
    return _support_feedback_service
