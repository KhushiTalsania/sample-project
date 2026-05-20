"""
Centralized JWT Handler

This module provides unified JWT token handling for all services.
"""

import jwt
from datetime import datetime, timedelta, timezone
import os
from typing import Dict, Optional, Any
from dotenv import load_dotenv
import secrets
import hashlib

load_dotenv()


class JWTHandler:
    """
    Centralized JWT token handler for all services.

    This class provides consistent JWT token creation, verification,
    and management across the entire monolithic application.
    """

    def __init__(self):
        # JWT Configuration
        self.secret_key = os.getenv("JWT_SECRET", "your_super_secret_jwt_key")
        self.algorithm = "HS256"
        self.access_token_expire_minutes = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
        )  # 24 hours
        self.access_token_expire_minutes_remember = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES_REMEMBER", "43200")
        )  # 30 days
        self.refresh_token_expire_days = int(
            os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")
        )

    def create_access_token(
        self, data: Dict[str, Any], remember_me: bool = False
    ) -> str:
        """
        Create JWT access token with user data.

        Args:
            data: User data to include in token
            remember_me: If True, token expires in 30 days, otherwise 24 hours

        Returns:
            JWT access token string
        """
        to_encode = data.copy()

        # Set expiration time
        expire_minutes = (
            self.access_token_expire_minutes_remember
            if remember_me
            else self.access_token_expire_minutes
        )

        expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
        to_encode.update(
            {"exp": expire, "iat": datetime.now(timezone.utc), "type": "access"}
        )

        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(self, user_id: str) -> str:
        """
        Create JWT refresh token.

        Args:
            user_id: User ID to include in token

        Returns:
            JWT refresh token string
        """
        to_encode = {
            "sub": user_id,
            "type": "refresh",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc)
            + timedelta(days=self.refresh_token_expire_days),
        }

        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify and decode JWT token.

        Args:
            token: JWT token to verify

        Returns:
            Decoded token payload or None if invalid
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def decode_token_without_verification(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Decode token without verification (for debugging/logging).

        Args:
            token: JWT token to decode

        Returns:
            Decoded token payload or None if invalid format
        """
        try:
            return jwt.decode(token, options={"verify_signature": False})
        except Exception:
            return None

    def generate_password_reset_token(self, email: str) -> str:
        """
        Generate secure password reset token.

        Args:
            email: User email address

        Returns:
            Secure password reset token
        """
        # Create a unique token using secrets and hash it
        random_token = secrets.token_urlsafe(32)
        token_data = f"{email}:{random_token}:{datetime.now(timezone.utc).isoformat()}"

        # Hash the token for security
        hashed_token = hashlib.sha256(token_data.encode()).hexdigest()
        return hashed_token

    def create_session_token(self, user_id: str, session_id: str) -> str:
        """
        Create session-specific token.

        Args:
            user_id: User ID
            session_id: Session ID

        Returns:
            Session JWT token
        """
        to_encode = {
            "sub": user_id,
            "session_id": session_id,
            "type": "session",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc)
            + timedelta(minutes=self.access_token_expire_minutes),
        }

        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def create_simple_signup_token(self, email: str, role: str = "moderator") -> str:
        """
        Create a simple Base64 encoded token with payload data.
        This token contains all the information needed and can be decoded.

        Args:
            email: User email address
            role: User role (default: moderator)

        Returns:
            Simple Base64 encoded token with payload
        """
        import base64
        import json
        import secrets

        # Create token payload
        payload = {
            "email": email,
            "role": role,
            "type": "moderator_signup",
            "isvalid": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "random": secrets.token_urlsafe(8),  # Add some randomness
        }

        # Convert to JSON and encode with Base64
        payload_json = json.dumps(payload)
        payload_encoded = base64.b64encode(payload_json.encode()).decode()

        # Add a simple signature part
        signature = secrets.token_urlsafe(8)

        # Create final token: payload_signature
        token = f"{payload_encoded}_{signature}"

        return token

    def decode_simple_signup_token(self, token: str) -> dict:
        """
        Decode a simple signup token to get the payload data.

        Args:
            token: The token to decode

        Returns:
            Dictionary with token payload or None if invalid
        """
        try:
            import base64
            import json

            # Split token into payload and signature
            if "_" not in token:
                return None

            payload_encoded, signature = token.split("_", 1)

            # Decode Base64 payload
            payload_json = base64.b64decode(payload_encoded).decode("utf-8")
            payload = json.loads(payload_json)

            # Check if token is not older than 7 days
            created_at = datetime.fromisoformat(
                payload["created_at"].replace("Z", "+00:00")
            )
            if datetime.now(timezone.utc) - created_at > timedelta(days=7):
                return None

            return payload

        except Exception:
            return None

    def create_moderator_signup_token(self, email: str, role: str = "moderator") -> str:
        """
        Create a proper JWT token for moderator signup.

        Args:
            email: User email address
            role: User role (default: moderator)

        Returns:
            JWT token for moderator signup
        """
        to_encode = {
            "email": email,
            "role": role,
            "type": "moderator_signup",
            "is_valid": True,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc)
            + timedelta(minutes=1),  # 1 minute expiration for testing
        }

        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def verify_moderator_signup_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify and decode moderator signup JWT token.
        Note: Expiration is ignored for moderator signup tokens.

        Args:
            token: JWT token to verify

        Returns:
            Decoded token payload or None if invalid
        """
        try:
            # Decode token without verifying expiration
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"verify_exp": False},  # Skip expiration verification
            )

            # Check if it's a moderator signup token
            if payload.get("type") != "moderator_signup":
                return None

            # Check if token is marked as valid
            if payload.get("is_valid") is not True:
                return None

            return payload
        except jwt.InvalidTokenError:
            return None


# Global JWT handler instance
_jwt_handler: Optional[JWTHandler] = None


def get_jwt_handler() -> JWTHandler:
    """Get the global JWT handler instance"""
    global _jwt_handler
    if _jwt_handler is None:
        _jwt_handler = JWTHandler()
    return _jwt_handler
