# """
# Centralized Email Service

# This module provides unified email functionality for all services.
# """

# import os
# import aiosmtplib
# from email.mime.text import MIMEText
# from email.mime.multipart import MIMEMultipart
# from typing import Optional, List, Dict, Any
# import logging
# from dotenv import load_dotenv

# load_dotenv()
# logger = logging.getLogger(__name__)

# class EmailService:
#     """Centralized email service for all services"""
    
#     def __init__(self):
#         self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
#         self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
#         self.smtp_username = os.getenv('SMTP_USERNAME', 'techtic.priyaagrawal@gmail.com')
#         self.smtp_password = os.getenv('SMTP_PASSWORD', 'rfhhgzfdiwxrjssd')
#         self.from_email = os.getenv('FROM_EMAIL', self.smtp_username)
#         self.use_ssl = os.getenv('SMTP_USE_SSL', 'true').lower() == 'true'
        
#         logger.info(f"📧 Email service initialized: {self.smtp_server}:{self.smtp_port}")
#         logger.info(f"📧 Using STARTTLS for port {self.smtp_port} (Gmail compatible)")
    
#     async def send_email(
#         self, 
#         to_email: str, 
#         subject: str, 
#         body: str, 
#         is_html: bool = False,
#         cc: Optional[List[str]] = None,
#         bcc: Optional[List[str]] = None
#     ) -> bool:
#         """Send email with optional CC and BCC"""
#         try:
#             msg = MIMEMultipart('alternative')
#             msg['Subject'] = subject
#             msg['From'] = self.from_email
#             msg['To'] = to_email
            
#             if cc:
#                 msg['Cc'] = ', '.join(cc)
#             if bcc:
#                 msg['Bcc'] = ', '.join(bcc)
            
#             # Add body
#             if is_html:
#                 msg.attach(MIMEText(body, 'html'))
#             else:
#                 msg.attach(MIMEText(body, 'plain'))
            
#             # Send email with proper Gmail configuration
#             logger.info(f"📧 Attempting to send email to {to_email} via {self.smtp_server}:{self.smtp_port}")
            
#             # Try with STARTTLS first (recommended for port 587)
#             try:
#                 await aiosmtplib.send(
#                     msg,
#                     hostname=self.smtp_server,
#                     port=self.smtp_port,
#                     start_tls=True,
#                     use_tls=False,
#                     username=self.smtp_username,
#                     password=self.smtp_password,
#                 )
#                 logger.info(f"✅ Email sent successfully to {to_email} using STARTTLS")
#                 return True
#             except Exception as starttls_error:
#                 logger.warning(f"⚠️ STARTTLS failed, trying alternative method: {starttls_error}")
                
#                 # Fallback: Try with different TLS settings
#                 try:
#                     await aiosmtplib.send(
#                         msg,
#                         hostname=self.smtp_server,
#                         port=self.smtp_port,
#                         start_tls=False,
#                         use_tls=True,
#                         username=self.smtp_username,
#                         password=self.smtp_password,
#                     )
#                     logger.info(f"✅ Email sent successfully to {to_email} using TLS fallback")
#                     return True
#                 except Exception as e:
#                     logger.error(f"❌ Failed to send email on port {self.smtp_port}: {e}")
#                     raise e
            
#         except Exception as e:
#             logger.error(f"❌ Failed to send email to {to_email}: {e}")
#             return False

# # Global email service instance
# _email_service: Optional[EmailService] = None

# def get_email_service() -> EmailService:
#     """Get the global email service instance"""
#     global _email_service
#     if _email_service is None:
#         _email_service = EmailService()
#     return _email_service

# async def send_email(
#     to_email: str, 
#     subject: str, 
#     body: str, 
#     is_html: bool = False,
#     cc: Optional[List[str]] = None,
#     bcc: Optional[List[str]] = None
# ) -> bool:
#     """Convenience function to send email using the global email service"""
#     email_service = get_email_service()
#     return await email_service.send_email(to_email, subject, body, is_html, cc, bcc) 


import os
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Cc, Bcc
from python_http_client.exceptions import HTTPError
from typing import Optional, List
from dotenv import load_dotenv
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import traceback

load_dotenv()
logger = logging.getLogger(__name__)

# Thread executor for async compatibility
executor = ThreadPoolExecutor()


class EmailService:
    """Centralized SendGrid email service"""

    def __init__(self):
        self.api_key = os.getenv("SENDGRID_API_KEY")
        self.from_email = os.getenv("FROM_EMAIL")
        print(self.from_email,"self.from_emailself.from_emailself.from_emailself.from_email")
        if not self.api_key:
            raise ValueError("❌ SENDGRID_API_KEY not found in environment variables")

        # Validate API key format (SendGrid API keys typically start with "SG.")
        if not self.api_key.startswith("SG."):
            logger.warning(f"⚠️ SendGrid API key doesn't start with 'SG.' - might be invalid")
            logger.warning(f"   API key format: {self.api_key[:10]}...")

        # Validate from_email format
        if "@" not in self.from_email:
            logger.warning(f"⚠️ FROM_EMAIL '{self.from_email}' doesn't look like a valid email address")

        logger.info(f"📧 SendGrid email service initialized | From: {self.from_email}")

    def _send_sync(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> bool:
        """Internal sync method to send email via SendGrid"""
        try:
            message = Mail(
                from_email=Email(self.from_email),
                to_emails=[To(to_email)],
                subject=subject,
                html_content=body if is_html else None,
                plain_text_content=body if not is_html else None,
            )

            # Add CC and BCC if provided
            if cc:
                message.cc = [Cc(email) for email in cc]
            if bcc:
                message.bcc = [Bcc(email) for email in bcc]

            sg = SendGridAPIClient(self.api_key)
            response = sg.send(message)

            if 200 <= response.status_code < 300:
                logger.info(f"✅ Email sent to {to_email} | Status: {response.status_code}")
                return True
            else:
                logger.warning(f"⚠️ Unexpected SendGrid response: {response.status_code}")
                logger.warning(f"Response body: {response.body}")
                return False

        except HTTPError as e:
            # Handle SendGrid/HTTP-related errors
            try:
                error_json = json.loads(e.body)
                logger.error(f"❌ SendGrid HTTPError: {json.dumps(error_json, indent=2)}")
            except Exception:
                logger.error(f"❌ SendGrid HTTPError: {e.body}")
            logger.error(f"   Status Code: {getattr(e, 'status_code', 'N/A')}")
            logger.error(f"   Headers: {getattr(e, 'headers', {})}")
            logger.error("💡 Troubleshooting tips:")
            logger.error("   - Verify your API key is correct and active")
            logger.error("   - Ensure 'Mail Send' permissions are enabled")
            logger.error(f"   - Confirm sender '{self.from_email}' is verified in SendGrid")
            return False

        except Exception as e:
            logger.error(f"❌ Unexpected error sending email to {to_email}: {type(e).__name__}: {e}")
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return False

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> bool:
        """Async wrapper to send email via SendGrid (compatible with FastAPI)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            executor,
            self._send_sync,
            to_email,
            subject,
            body,
            is_html,
            cc,
            bcc,
        )


# Global instance
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Get the global SendGrid email service instance"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service


async def send_email(
    to_email: str,
    subject: str,
    body: str,
    is_html: bool = False,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
) -> bool:
    """Convenience async function to send email using the global service"""
    email_service = get_email_service()
    return await email_service.send_email(to_email, subject, body, is_html, cc, bcc)
