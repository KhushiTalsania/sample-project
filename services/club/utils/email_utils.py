"""
Email Utility Functions

This module provides email functionality for club-related notifications.
It handles sending emails to admins for club approval requests.
"""

import logging
from typing import List, Dict, Optional
import os
from datetime import datetime
from core.utils.email_service import send_email as send_email_centralized

# Configure logging
logger = logging.getLogger(__name__)

class EmailService:
    """Service for sending emails (now using centralized email service)"""
    
    def __init__(self):
        # Email configuration from environment variables (kept for compatibility)
        self.from_email = os.getenv("FROM_EMAIL", "noreply@bettingapp.com")
        self.from_name = os.getenv("FROM_NAME", "Betting App")
    
    async def send_club_approval_email(self, club_data: Dict, admin_emails: List[str]) -> bool:
        """
        Send club approval request email to all admins
        
        Args:
            club_data: Dictionary containing club information
            admin_emails: List of admin email addresses
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            if not admin_emails:
                logger.warning("No admin emails provided for club approval notification")
                return False
            
            # Prepare email content
            subject = f"Club Approval Request: {club_data.get('club_name', 'Unknown Club')}"
            html_content = self._create_club_approval_email_html(club_data)
            text_content = self._create_club_approval_email_text(club_data)
            
            # Send email to all admins
            success = await self._send_email(
                to_emails=admin_emails,
                subject=subject,
                html_content=html_content,
                text_content=text_content
            )
            
            if success:
                logger.info(f"Club approval email sent successfully to {len(admin_emails)} admins for club: {club_data.get('club_name')}")
            else:
                logger.error(f"Failed to send club approval email for club: {club_data.get('club_name')}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending club approval email: {e}")
            return False
    
    def _create_club_approval_email_html(self, club_data: Dict) -> str:
        """Create HTML content for club approval email"""
        
        club_name = club_data.get('club_name', 'Unknown Club')
        club_id = club_data.get('club_id', 'N/A')
        club_name_based_id = club_data.get('club_name_based_id', 'N/A')
        captain_name = club_data.get('captain_name', 'Unknown Captain')
        captain_email = club_data.get('captain_email', 'N/A')
        created_at = club_data.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        moderator_count = club_data.get('moderator_count', 0)
        member_count = club_data.get('member_count', 0)
        description = club_data.get('description', 'No description provided')
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Club Approval Request</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background-color: #2c3e50;
                    color: white;
                    padding: 20px;
                    text-align: center;
                    border-radius: 5px 5px 0 0;
                }}
                .content {{
                    background-color: #f8f9fa;
                    padding: 20px;
                    border-radius: 0 0 5px 5px;
                }}
                .club-info {{
                    background-color: white;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 15px 0;
                    border-left: 4px solid #3498db;
                }}
                .action-button {{
                    display: inline-block;
                    background-color: #3498db;
                    color: white;
                    padding: 10px 20px;
                    text-decoration: none;
                    border-radius: 5px;
                    margin: 10px 5px;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 20px;
                    color: #666;
                    font-size: 12px;
                }}
                .highlight {{
                    background-color: #fff3cd;
                    padding: 10px;
                    border-radius: 5px;
                    border-left: 4px solid #ffc107;
                    margin: 10px 0;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🏆 Club Approval Request</h1>
                <p>A new club is waiting for your approval</p>
            </div>
            
            <div class="content">
                <div class="highlight">
                    <strong>Action Required:</strong> Please review and approve or reject this club request.
                </div>
                
                <h2>Club Information</h2>
                <div class="club-info">
                    <p><strong>Club Name:</strong> {club_name}</p>
                    <p><strong>Club ID:</strong> {club_id}</p>
                    <p><strong>Name-based ID:</strong> {club_name_based_id}</p>
                    <p><strong>Captain:</strong> {captain_name} ({captain_email})</p>
                    <p><strong>Created:</strong> {created_at}</p>
                    <p><strong>Moderators:</strong> {moderator_count}</p>
                    <p><strong>Members:</strong> {member_count}</p>
                    <p><strong>Description:</strong> {description}</p>
                </div>
                
                <h2>Next Steps</h2>
                <p>Please review the club details and take appropriate action:</p>
                <ul>
                    <li>✅ <strong>Approve:</strong> If the club meets all requirements and guidelines</li>
                    <li>❌ <strong>Reject:</strong> If the club doesn't meet requirements or violates policies</li>
                </ul>
                
                <p><strong>Note:</strong> You can approve or reject this club through the admin panel.</p>
                
                <div class="footer">
                    <p>This is an automated notification from the Betting App system.</p>
                    <p>Please do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html_content
    
    def _create_club_approval_email_text(self, club_data: Dict) -> str:
        """Create plain text content for club approval email"""
        
        club_name = club_data.get('club_name', 'Unknown Club')
        club_id = club_data.get('club_id', 'N/A')
        club_name_based_id = club_data.get('club_name_based_id', 'N/A')
        captain_name = club_data.get('captain_name', 'Unknown Captain')
        captain_email = club_data.get('captain_email', 'N/A')
        created_at = club_data.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        moderator_count = club_data.get('moderator_count', 0)
        member_count = club_data.get('member_count', 0)
        description = club_data.get('description', 'No description provided')
        
        text_content = f"""
CLUB APPROVAL REQUEST
====================

A new club is waiting for your approval.

CLUB INFORMATION:
-----------------
Club Name: {club_name}
Club ID: {club_id}
Name-based ID: {club_name_based_id}
Captain: {captain_name} ({captain_email})
Created: {created_at}
Moderators: {moderator_count}
Members: {member_count}
Description: {description}

ACTION REQUIRED:
----------------
Please review the club details and take appropriate action:

✅ APPROVE: If the club meets all requirements and guidelines
❌ REJECT: If the club doesn't meet requirements or violates policies

Note: You can approve or reject this club through the admin panel.

---
This is an automated notification from the Betting App system.
Please do not reply to this email.
        """
        
        return text_content
    
    async def _send_email(self, to_emails: List[str], subject: str, html_content: str, text_content: str) -> bool:
        """
        Send email to multiple recipients using centralized email service (SendGrid)
        
        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            html_content: HTML email content
            text_content: Plain text email content (not used with SendGrid, but kept for compatibility)
            
        Returns:
            bool: True if email sent successfully to all recipients, False otherwise
        """
        try:
            success_count = 0
            for email in to_emails:
                result = await send_email_centralized(
                    to_email=email,
                    subject=subject,
                    body=html_content,
                    is_html=True
                )
                if result:
                    success_count += 1
            
            if success_count == len(to_emails):
                logger.info(f"Email sent successfully to {len(to_emails)} recipients")
                return True
            else:
                logger.warning(f"Email sent to {success_count}/{len(to_emails)} recipients")
                return False
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

# Global email service instance
email_service = EmailService()

async def send_club_approval_notification(club_data: Dict, admin_emails: List[str]) -> bool:
    """
    Convenience function to send club approval notification
    
    Args:
        club_data: Dictionary containing club information
        admin_emails: List of admin email addresses
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    return await email_service.send_club_approval_email(club_data, admin_emails)

async def send_email_to_members(to_email: str, subject: str, message: str) -> bool:
    """
    Send email to a single member using centralized email service (SendGrid)
    
    Args:
        to_email: Email address of the member
        subject: Email subject
        message: HTML email content
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Use centralized email service (SendGrid)
        result = await send_email_centralized(
            to_email=to_email,
            subject=subject,
            body=message,
            is_html=True
        )
        
        if result:
            logger.info(f"Email sent successfully to {to_email}")
        else:
            logger.error(f"Failed to send email to {to_email}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False
