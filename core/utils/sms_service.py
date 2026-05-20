"""
Centralized SMS Service

This module provides unified SMS functionality for all services.
"""

import os
from twilio.rest import Client
from typing import Optional
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class SMSService:
    """Centralized SMS service using Twilio"""
    
    def __init__(self):
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        self.phone_number = os.getenv('TWILIO_PHONE_NUMBER')
        
        self.client = None
        if self.account_sid and self.auth_token:
            try:
                self.client = Client(self.account_sid, self.auth_token)
                logger.info("✅ Twilio SMS service initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Twilio client: {e}")
        else:
            logger.warning("⚠️ Twilio credentials not found - SMS functionality disabled")
    
    async def send_sms(self, to_number: str, message: str) -> bool:
        """Send SMS message"""
        if not self.client:
            logger.error("❌ SMS service not initialized")
            return False
        
        try:
            # Format phone number
            formatted_number = to_number if to_number.startswith('+') else f"+{to_number}"
            
            message_obj = self.client.messages.create(
                body=message,
                from_=self.phone_number,
                to=formatted_number
            )
            
            logger.info(f"✅ SMS sent successfully. SID: {message_obj.sid}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send SMS to {to_number}: {e}")
            return False
    
    async def send_otp(self, phone_number: str, otp: str, expiry_minutes: int = 5) -> bool:
        """Send OTP SMS"""
        message = f"Your verification code is: {otp}. Valid for {expiry_minutes} minutes."
        return await self.send_sms(phone_number, message)

# Global SMS service instance
_sms_service: Optional[SMSService] = None

def get_sms_service() -> SMSService:
    """Get the global SMS service instance"""
    global _sms_service
    if _sms_service is None:
        _sms_service = SMSService()
    return _sms_service 