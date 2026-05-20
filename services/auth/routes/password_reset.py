from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from ..models import ForgotPasswordRequest, ForgotPasswordResponse, ResetPasswordRequest, ResetPasswordResponse
from ..utils import (
    get_user_by_email, generate_password_reset_token, store_password_reset_token,
    send_password_reset_email, verify_password_reset_token, delete_password_reset_token,
    update_user_password, get_club_count_for_captain, update_user_club_count
)

router = APIRouter()

# @router.post("/test-smtp")
# async def test_smtp():
#     """
#     Test SMTP connection and email sending
#     """
#     try:
#         print("🧪 Testing SMTP connection...")
#         success = await test_smtp_connection()
        
#         if success:
#             return {
#                 "message": "SMTP test successful! Email configuration is working.",
#                 "success": True
#             }
#         else:
#             return JSONResponse(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 content={
#                     "message": "SMTP test failed. Check your email configuration.",
#                     "success": False,
#                     "error": "smtp_test_failed"
#                 }
#             )
#     except Exception as e:
#         return JSONResponse(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             content={
#                 "message": f"SMTP test error: {str(e)}",
#                 "success": False,
#                 "error": str(e)
#             }
#         )

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(request: ForgotPasswordRequest):
    """
    Initiate password reset process
    """
    try:
        print(f"🔐 Forgot password request for: {request.email}")
        
        # Get user by email
        user = await get_user_by_email(request.email)
        print(user,"useruser")
        
        if not user:
            print(f"❌ User not found with email: {request.email}")
            return JSONResponse(
                status_code=404,
                content={
                    "message": "User not found with this email address",
                    "success": False,
                    "error": "user_not_found"
                }
            )
        
        print(f"✅ User found: {user.get('full_name', 'Unknown')}")
        
        # Generate reset token
        token = generate_password_reset_token()
        print(f"🔑 Generated reset token: {token[:10]}...")
        
        # Store token in database
        stored = await store_password_reset_token(str(user["_id"]), token)
        if not stored:
            print("❌ Failed to store reset token")
            return ForgotPasswordResponse(
                message="Failed to process password reset request. Please try again.",
                success=False,
                error="token_storage_failed"
            )
        
        print("✅ Reset token stored successfully")
        
        # Send reset email
        email_sent = await send_password_reset_email(
            request.email, 
            token, 
            user.get('full_name', 'User')
        )
        print(email_sent,"email_sent")
        
        if email_sent:
            print("✅ Password reset email sent successfully")
            return ForgotPasswordResponse(
                message="Password reset link has been sent to your email address",
                success=True,
                error=None
            )
        else:
            print("⚠️ Failed to send email, but token was stored")
            return ForgotPasswordResponse(
                message="Password reset link generated but failed to send email. Please try again.",
                success=False,
                error="email_send_failed"
            )
        
    except Exception as e:
        print(f"❌ Forgot password error: {e}")
        return ForgotPasswordResponse(
            message="An error occurred while processing your request. Please try again.",
            success=False,
            error="internal_server_error"
        )

@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(request: ResetPasswordRequest):
    """
    Reset password using token from email
    """
    try:
        print(f"🔐 Reset password request with token: {request.token[:10]}...")
        
        # Verify reset token
        token_doc = await verify_password_reset_token(request.token)
        if not token_doc:
            print("❌ Invalid or expired reset token")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "message": "This link is invalid or expired. Please request a new reset link.",
                    "success": False,
                    "error": "invalid_token"
                }
            )
        
        print(f"✅ Reset token verified for user: {token_doc['user_id']}")
        print(f"🔑 Token document: {token_doc}")
        
        # Update user password
        password_updated = await update_user_password(
            token_doc['user_id'], 
            request.new_password
        )
        
        if not password_updated:
            print("❌ Failed to update user password")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "message": "Failed to reset password. Please try again.",
                    "success": False,
                    "error": "update_failed"
                }
            )
        
        print("✅ User password updated successfully")
        
        # Delete the used token
        await delete_password_reset_token(request.token)
        print("✅ Reset token deleted after use")
        
        # Get updated user details to include club_count in response if needed
        try:
            from ..db import get_user_collection
            from bson import ObjectId
            
            users_collection = get_user_collection()
            user = await users_collection.find_one({"_id": ObjectId(token_doc['user_id'])})
            
            if user and user.get("role") == "Captain":
                # Update club count for captain
                try:
                    club_count = await get_club_count_for_captain(str(user["_id"]))
                    await update_user_club_count(str(user["_id"]), club_count)
                    print(f"👑 Captain {user.get('full_name', 'Unknown')} club count updated to {club_count} after password reset")
                except Exception as e:
                    print(f"⚠️ Could not update club count for captain after password reset: {e}")
        except Exception as e:
            print(f"⚠️ Could not get user details after password reset: {e}")
        
        return {
            "message": "Password successfully reset. Please login.",
            "success": True
        }
        
    except Exception as e:
        print(f"❌ Error in password reset: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message": "Internal server error. Please try again.",
                "success": False,
                "error": str(e)
            }
        ) 