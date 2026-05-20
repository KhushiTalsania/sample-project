import logging
from typing import Optional
import os
from core.utils.email_service import send_email as send_email_centralized

logger = logging.getLogger(__name__)

async def send_moderator_invitation_email(
    to_email: str,
    moderator_name: str,
    club_name: str,
    captain_name: str,
    club_id: str,
    invitation_token: str
) -> bool:
    """
    Send moderator invitation email
    
    Args:
        to_email: Email address of the potential moderator
        moderator_name: Name of the potential moderator
        club_name: Name of the club
        captain_name: Name of the club captain
        club_id: Club ID
        invitation_token: Unique token for invitation acceptance
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        
        # Create HTML body
        html_body = f"""
        <html>
        <body>
            <h2>🎯 Moderator Invitation</h2>
            <p>Hello {moderator_name},</p>
            
            <p>You have been invited by <strong>{captain_name}</strong> to become a moderator at <strong>{club_name}</strong>.</p>
            
            <p>As a moderator, you will have the ability to:</p>
            <ul>
                <li>Help manage club discussions and activities</li>
                <li>Ensure club rules are followed</li>
                <li>Support club members</li>
                <li>Contribute to club growth and success</li>
            </ul>
            
            <p><strong>Important Note:</strong> The first moderator is free, but additional moderators cost $9.95/month per moderator.</p>
            
            <div style="margin: 30px 0;">
                <a href="{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/moderator-invitation?token={invitation_token}&club_id={club_id}&email={to_email}" 
                   style="background-color: #4CAF50; color: white; padding: 14px 28px; text-decoration: none; border-radius: 4px; display: inline-block;">
                    Accept Invitation
                </a>
                
                <a href="{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/moderator-invitation?token={invitation_token}&club_id={club_id}&email={to_email}&response=decline" 
                   style="background-color: #f44336; color: white; padding: 14px 28px; text-decoration: none; border-radius: 4px; display: inline-block; margin-left: 10px;">
                    Decline Invitation
                </a>
            </div>
            
            <p>If you have any questions, please contact the club captain.</p>
            
            <p>Best regards,<br>The {club_name} Team</p>
            
            <hr>
            <p style="font-size: 12px; color: #666;">
                This invitation was sent by {captain_name} for the club {club_name}. 
                If you did not expect this invitation, please ignore this email.
            </p>
        </body>
        </html>
        """
        
        # Create plain text body
        text_body = f"""
        Moderator Invitation
        
        Hello {moderator_name},
        
        You have been invited by {captain_name} to become a moderator at {club_name}.
        
        As a moderator, you will have the ability to:
        - Help manage club discussions and activities
        - Ensure club rules are followed
        - Support club members
        - Contribute to club growth and success
        
        Important Note: The first moderator is free, but additional moderators cost $9.95/month per moderator.
        
        To respond to this invitation, please visit:
        {os.getenv('FRONTEND_URL', 'http://localhost:3000')}/moderator-invitation?token={invitation_token}&club_id={club_id}&email={to_email}
        
        If you have any questions, please contact the club captain.
        
        Best regards,
        The {club_name} Team
        
        ---
        This invitation was sent by {captain_name} for the club {club_name}.
        If you did not expect this invitation, please ignore this email.
        """
        
        # Use centralized email service (SendGrid)
        result = await send_email_centralized(
            to_email=to_email,
            subject=f"Invitation to become a Moderator at {club_name}",
            body=html_body,
            is_html=True
        )
        
        if result:
            logger.info(f"Moderator invitation email sent successfully to {to_email}")
        else:
            logger.error(f"Failed to send moderator invitation email to {to_email}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to send moderator invitation email to {to_email}: {e}")
        return False

async def send_email(to_email: str, subject: str, html_content: str, text_content: str) -> bool:
    """
    Send email with HTML and text content using centralized email service (SendGrid)
    
    Args:
        to_email: Email address of the recipient
        subject: Email subject
        html_content: HTML email content
        text_content: Plain text email content (not used with SendGrid, but kept for compatibility)
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Use centralized email service (SendGrid)
        # SendGrid handles both HTML and plain text automatically
        result = await send_email_centralized(
            to_email=to_email,
            subject=subject,
            body=html_content,
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

async def send_moderator_response_notification(
    captain_email: str,
    moderator_name: str,
    club_name: str,
    response: str
) -> bool:
    """
    Send notification to captain about moderator response
    
    Args:
        captain_email: Email address of the club captain
        moderator_name: Name of the moderator
        club_name: Name of the club
        response: Moderator's response ('accept' or 'decline')
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        
        # Create HTML body
        status_emoji = "✅" if response == "accept" else "❌"
        status_text = "accepted" if response == "accept" else "declined"
        
        html_body = f"""
        <html>
        <body>
            <h2>{status_emoji} Moderator Response</h2>
            <p>Hello Club Captain,</p>
            
            <p><strong>{moderator_name}</strong> has {status_text} your invitation to become a moderator at <strong>{club_name}</strong>.</p>
            
            <p>Response: <strong>{response.upper()}</strong></p>
            
            <p>You can view the current status of all moderator invitations in your club dashboard.</p>
            
            <p>Best regards,<br>The {club_name} Team</p>
        </body>
        </html>
        """
        
        # Create plain text body
        text_body = f"""
        Moderator Response
        
        Hello Club Captain,
        
        {moderator_name} has {status_text} your invitation to become a moderator at {club_name}.
        
        Response: {response.upper()}
        
        You can view the current status of all moderator invitations in your club dashboard.
        
        Best regards,
        The {club_name} Team
        """
        
        # Use centralized email service (SendGrid)
        result = await send_email_centralized(
            to_email=captain_email,
            subject=f"Moderator Response: {moderator_name} has {response}ed",
            body=html_body,
            is_html=True
        )
        
        if result:
            logger.info(f"Moderator response notification sent successfully to captain {captain_email}")
        else:
            logger.error(f"Failed to send moderator response notification to captain {captain_email}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to send moderator response notification to captain {captain_email}: {e}")
        return False
