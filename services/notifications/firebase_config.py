# """
# Firebase Admin SDK Configuration

# This module initializes and manages the Firebase Admin SDK for
# push notification functionality using Firebase Cloud Messaging (FCM).
# """

# import firebase_admin
# from firebase_admin import credentials, messaging
# import os
# import logging
# from typing import Optional

# logger = logging.getLogger(__name__)

# # Global Firebase app instance
# _firebase_app: Optional[firebase_admin.App] = None

# def initialize_firebase() -> firebase_admin.App:
#     """
#     Initialize Firebase Admin SDK with service account credentials.
    
#     Returns:
#         firebase_admin.App: Initialized Firebase app instance
        
#     Raises:
#         Exception: If Firebase initialization fails
#     """
#     global _firebase_app
    
#     # Return existing instance if already initialized
#     if _firebase_app is not None:
#         logger.info("Firebase Admin SDK already initialized")
#         return _firebase_app
    
#     try:
#         # Path to Firebase service account JSON file
#         # Located at project root
#         firebase_credentials_path = os.path.join(
#             os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
#             'simulated-betting-mvp-firebase-adminsdk-fbsvc-9fa078213b.json'
#         )
        
#         # Check if credentials file exists
#         if not os.path.exists(firebase_credentials_path):
#             raise FileNotFoundError(
#                 f"Firebase credentials file not found at: {firebase_credentials_path}\n"
#                 "Please ensure the Firebase service account JSON file is placed in the project root."
#             )
        
#         # Initialize Firebase with credentials
#         cred = credentials.Certificate(firebase_credentials_path)
#         _firebase_app = firebase_admin.initialize_app(cred)
        
#         logger.info("✅ Firebase Admin SDK initialized successfully")
#         logger.info(f"📁 Credentials loaded from: {firebase_credentials_path}")
        
#         return _firebase_app
        
#     except Exception as e:
#         logger.error(f"❌ Failed to initialize Firebase Admin SDK: {e}")
#         raise

# def get_firebase_app() -> Optional[firebase_admin.App]:
#     """
#     Get the initialized Firebase app instance.
    
#     Returns:
#         Optional[firebase_admin.App]: Firebase app instance or None if not initialized
#     """
#     return _firebase_app

# def send_push_notification(
#     token: str,
#     title: str,
#     body: str,
#     data: Optional[dict] = None,
#     image_url: Optional[str] = None,
#     sound: str = "default",
#     badge: Optional[int] = None,
#     priority: str = "high"
# ) -> dict:
#     """
#     Send a push notification to a specific device token.
    
#     Args:
#         token: FCM device token
#         title: Notification title
#         body: Notification body/message
#         data: Additional data payload (optional)
#         image_url: Image URL for rich notification (optional)
#         sound: Notification sound (default: "default")
#         badge: Badge count for iOS (optional)
#         priority: Notification priority ("high" or "normal")
        
#     Returns:
#         dict: Response with success status and message ID or error
        
#     Raises:
#         Exception: If Firebase is not initialized
#     """
#     if _firebase_app is None:
#         raise Exception("Firebase Admin SDK not initialized. Call initialize_firebase() first.")
    
#     try:
#         # Build notification payload
#         notification = messaging.Notification(
#             title=title,
#             body=body,
#             image=image_url
#         )
        
#         # Build Android config
#         android_config = messaging.AndroidConfig(
#             priority=priority,
#             notification=messaging.AndroidNotification(
#                 sound=sound,
#                 priority=priority
#             )
#         )
        
#         # Build APNs (iOS) config
#         apns_config = messaging.APNSConfig(
#             payload=messaging.APNSPayload(
#                 aps=messaging.Aps(
#                     sound=sound,
#                     badge=badge
#                 )
#             )
#         )
        
#         # Create message
#         message = messaging.Message(
#             notification=notification,
#             data=data or {},
#             token=token,
#             android=android_config,
#             apns=apns_config
#         )
        
#         # Send message
#         response = messaging.send(message)
        
#         logger.info(f"✅ Successfully sent notification to token: {token[:20]}...")
        
#         return {
#             "success": True,
#             "message_id": response,
#             "token": token
#         }
        
#     except messaging.UnregisteredError:
#         logger.warning(f"⚠️ Token is no longer valid (unregistered): {token[:20]}...")
#         return {
#             "success": False,
#             "error": "unregistered_token",
#             "message": "Device token is no longer valid",
#             "token": token
#         }
        
#     except messaging.InvalidArgumentError as e:
#         logger.error(f"❌ Invalid argument for token {token[:20]}...: {e}")
#         return {
#             "success": False,
#             "error": "invalid_argument",
#             "message": str(e),
#             "token": token
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Failed to send notification to token {token[:20]}...: {e}")
#         return {
#             "success": False,
#             "error": "send_failed",
#             "message": str(e),
#             "token": token
#         }

# def send_multicast_notification(
#     tokens: list[str],
#     title: str,
#     body: str,
#     data: Optional[dict] = None,
#     image_url: Optional[str] = None,
#     sound: str = "default",
#     badge: Optional[int] = None,
#     priority: str = "high"
# ) -> dict:
#     """
#     Send a push notification to multiple device tokens (up to 500 tokens).
    
#     Args:
#         tokens: List of FCM device tokens
#         title: Notification title
#         body: Notification body/message
#         data: Additional data payload (optional)
#         image_url: Image URL for rich notification (optional)
#         sound: Notification sound (default: "default")
#         badge: Badge count for iOS (optional)
#         priority: Notification priority ("high" or "normal")
        
#     Returns:
#         dict: Response with success/failure counts and invalid tokens
        
#     Raises:
#         Exception: If Firebase is not initialized
#     """
#     if _firebase_app is None:
#         raise Exception("Firebase Admin SDK not initialized. Call initialize_firebase() first.")
    
#     if not tokens or len(tokens) == 0:
#         return {
#             "success": True,
#             "success_count": 0,
#             "failure_count": 0,
#             "invalid_tokens": []
#         }
    
#     try:
#         # Build notification payload
#         notification = messaging.Notification(
#             title=title,
#             body=body,
#             image=image_url
#         )
        
#         # Build Android config
#         android_config = messaging.AndroidConfig(
#             priority=priority,
#             notification=messaging.AndroidNotification(
#                 sound=sound,
#                 priority=priority
#             )
#         )
        
#         # Build APNs (iOS) config
#         apns_config = messaging.APNSConfig(
#             payload=messaging.APNSPayload(
#                 aps=messaging.Aps(
#                     sound=sound,
#                     badge=badge
#                 )
#             )
#         )
        
#         # Create multicast message
#         message = messaging.MulticastMessage(
#             notification=notification,
#             data=data or {},
#             tokens=tokens,
#             android=android_config,
#             apns=apns_config
#         )
        
#         # Send multicast message
#         response = messaging.send_multicast(message)
        
#         # Collect invalid tokens
#         invalid_tokens = []
#         if response.failure_count > 0:
#             for idx, send_response in enumerate(response.responses):
#                 if not send_response.success:
#                     if isinstance(send_response.exception, messaging.UnregisteredError):
#                         invalid_tokens.append(tokens[idx])
        
#         logger.info(
#             f"✅ Multicast notification sent: "
#             f"{response.success_count} succeeded, "
#             f"{response.failure_count} failed"
#         )
        
#         return {
#             "success": True,
#             "success_count": response.success_count,
#             "failure_count": response.failure_count,
#             "invalid_tokens": invalid_tokens
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Failed to send multicast notification: {e}")
#         return {
#             "success": False,
#             "error": str(e),
#             "success_count": 0,
#             "failure_count": len(tokens),
#             "invalid_tokens": []
#         }

# def send_topic_notification(
#     topic: str,
#     title: str,
#     body: str,
#     data: Optional[dict] = None,
#     image_url: Optional[str] = None,
#     sound: str = "default",
#     priority: str = "high"
# ) -> dict:
#     """
#     Send a push notification to a topic (for broadcast notifications).
    
#     Args:
#         topic: Topic name
#         title: Notification title
#         body: Notification body/message
#         data: Additional data payload (optional)
#         image_url: Image URL for rich notification (optional)
#         sound: Notification sound (default: "default")
#         priority: Notification priority ("high" or "normal")
        
#     Returns:
#         dict: Response with success status and message ID or error
        
#     Raises:
#         Exception: If Firebase is not initialized
#     """
#     if _firebase_app is None:
#         raise Exception("Firebase Admin SDK not initialized. Call initialize_firebase() first.")
    
#     try:
#         # Build notification payload
#         notification = messaging.Notification(
#             title=title,
#             body=body,
#             image=image_url
#         )
        
#         # Build Android config
#         android_config = messaging.AndroidConfig(
#             priority=priority,
#             notification=messaging.AndroidNotification(
#                 sound=sound,
#                 priority=priority
#             )
#         )
        
#         # Build APNs (iOS) config
#         apns_config = messaging.APNSConfig(
#             payload=messaging.APNSPayload(
#                 aps=messaging.Aps(
#                     sound=sound
#                 )
#             )
#         )
        
#         # Create message
#         message = messaging.Message(
#             notification=notification,
#             data=data or {},
#             topic=topic,
#             android=android_config,
#             apns=apns_config
#         )
        
#         # Send message
#         response = messaging.send(message)
        
#         logger.info(f"✅ Successfully sent notification to topic: {topic}")
        
#         return {
#             "success": True,
#             "message_id": response,
#             "topic": topic
#         }
        
#     except Exception as e:
#         logger.error(f"❌ Failed to send notification to topic {topic}: {e}")
#         return {
#             "success": False,
#             "error": str(e),
#             "topic": topic
#         }



"""
Optimized Firebase Admin SDK Setup and Notification Utility
"""

import os
import logging
from typing import Optional, List, Dict
import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)
_firebase_app: Optional[firebase_admin.App] = None


# ========================================
# INITIALIZATION
# ========================================
# def initialize_firebase() -> firebase_admin.App:
#     """Initialize Firebase Admin SDK if not already initialized."""
#     global _firebase_app
#     if _firebase_app:
#         return _firebase_app

#     try:
#         cred_path = os.path.join(
#             os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
#             "simulated-betting-mvp-firebase-adminsdk-fbsvc-9fa078213b.json",
#         )
#         if not os.path.exists(cred_path):
#             raise FileNotFoundError(f"Firebase credentials not found at {cred_path}")

#         _firebase_app = firebase_admin.initialize_app(credentials.Certificate(cred_path))
#         logger.info("✅ Firebase Admin SDK initialized successfully")
#         return _firebase_app
#     except Exception as e:
#         logger.error(f"❌ Firebase initialization failed: {e}")
#         raise


def initialize_firebase() -> firebase_admin.App:
    global _firebase_app
    if _firebase_app:
        return _firebase_app

    cred_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "simulated-mvp-firebase-adminsdk-fbsvc-08aefba120.json",
    )
    if not os.path.exists(cred_path):
        raise FileNotFoundError(f"Firebase credentials not found at {cred_path}")

    cred = credentials.Certificate(cred_path)

    # ✅ Explicitly specify the project ID
    _firebase_app = firebase_admin.initialize_app(
        cred, {"projectId": "simulated-mvp"}
    )

    print("🔥 Firebase initialized with project:", _firebase_app.project_id)
    return _firebase_app



def get_firebase_app() -> Optional[firebase_admin.App]:
    """Return the initialized Firebase app."""
    return _firebase_app


# ========================================
# INTERNAL HELPERS
# ========================================
def _check_initialized():
    if not _firebase_app:
        raise RuntimeError("Firebase Admin SDK not initialized. Call initialize_firebase() first.")


def _base_notification(title: str, body: str, image_url: Optional[str]) -> messaging.Notification:
    return messaging.Notification(title=title, body=body, image=image_url)


# def _platform_configs(sound: str, badge: Optional[int], priority: str):
#     return (
#         messaging.AndroidConfig(
#             priority=priority,
#             notification=messaging.AndroidNotification(sound=sound, priority=priority),
#         ),
#         messaging.APNSConfig(payload=messaging.APNSPayload(aps=messaging.Aps(sound=sound, badge=badge))),
#     )
def _platform_configs(sound: str = "default", badge: Optional[int] = None, priority: str = "high"):
    priority = priority.lower()
    android_priority = "high" if priority in ["high", "max"] else "normal"

    return (
        messaging.AndroidConfig(
            priority=android_priority,
            notification=messaging.AndroidNotification(sound=sound, notification_count=badge),
        ),
        messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound=sound, badge=badge)
            )
        ),
    )


# ========================================
# SEND NOTIFICATIONS
# ========================================
def send_push_notification(
    token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    image_url: Optional[str] = None,
    sound: str = "default",
    badge: Optional[int] = None,
    priority: str = "high",
) -> Dict:
    """Send notification to a single device token."""
    _check_initialized()
    try:
        android, apns = _platform_configs(sound, badge, priority)
        message = messaging.Message(
            # notification=_base_notification(title, body, image_url),
            data=data or {},
            token=token,
            # android=android,
            # apns=apns,
        )
        msg_id = messaging.send(message)
        logger.info(f"✅ Sent notification to token: {token[:20]}...")
        return {"success": True, "message_id": msg_id, "token": token}
    except Exception as e:
        logger.error(f"❌ Send failed for token {token[:20]}: {e}")
        return {"success": False, "error": str(e), "token": token}


def send_multicast_notification(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[dict] = None,
    image_url: Optional[str] = None,
    sound: str = "default",
    badge: Optional[int] = None,
    priority: str = "high",
) -> Dict:
    """Send notification to multiple device tokens (max 500)."""
    _check_initialized()
    if not tokens:
        return {"success": True, "success_count": 0, "failure_count": 0, "invalid_tokens": []}

    try:
        # android, apns = _platform_configs(sound, badge, priority)
        message = messaging.MulticastMessage(
            # notification=_base_notification(title, body, image_url),
            data=data or {},
            tokens=tokens,
            # android=android,
            # apns=apns,
        )
        # amey 04122025
        # message = messaging.MulticastMessage(
        #     notification=_base_notification(title, body, image_url),
        #     data={
        #         **(data or {}),
        #         "title": title,
        #         "body": body,
        #     },
        #     tokens=tokens,
        #     # android=android,
        #     # apns=apns,
        # )
        # message = messaging.MulticastMessage(
        #     data={
        #         **data,
        #         "title": title,
        #         "body": body,
        #     },
        #     tokens=tokens,
        # )
        res = messaging.send_each_for_multicast(message)
        print(res,"resresresres")
        print(res.responses,"res.responsesres.responsesres.responsesres.responses")
        # Log detailed error information for failures
        invalid = []
        for i, r in enumerate(res.responses):
            if not r.success:
                if isinstance(r.exception, messaging.UnregisteredError):
                    invalid.append(tokens[i])
                    logger.warning(f"⚠️ Unregistered token: {tokens[i][:20]}...")
                else:
                    # Log other types of errors
                    error_type = type(r.exception).__name__ if r.exception else "Unknown"
                    error_msg = str(r.exception) if r.exception else "No exception details"
                    logger.error(f"❌ Notification failed for token {tokens[i][:20]}...: {error_type} - {error_msg}")
        
        logger.info(f"✅ Multicast sent: {res.success_count} success, {res.failure_count} fail")
        return {
            "success": True,
            "success_count": res.success_count,
            "failure_count": res.failure_count,
            "invalid_tokens": invalid,
        }
    except Exception as e:
        logger.error(f"❌ Multicast send failed: {e}")
        return {"success": False, "error": str(e), "invalid_tokens": []}

def send_topic_notification(
    topic: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    image_url: Optional[str] = None,
    sound: str = "default",
    priority: str = "high",
) -> Dict:
    """Send a broadcast notification to all subscribers of a topic."""
    _check_initialized()
    try:
        android, apns = _platform_configs(sound, None, priority)
        msg = messaging.Message(
            # notification=_base_notification(title, body, image_url),
            data=data or {},
            topic=topic,
            # android=android,
            # apns=apns,
        )
        msg_id = messaging.send(msg)
        logger.info(f"✅ Sent topic notification: {topic}")
        return {"success": True, "message_id": msg_id, "topic": topic}
    except Exception as e:
        logger.error(f"❌ Topic send failed ({topic}): {e}")
        return {"success": False, "error": str(e), "topic": topic}
