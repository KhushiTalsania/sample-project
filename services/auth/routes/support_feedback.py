"""
Support & Feedback API Routes

This module provides API endpoints for submitting support and feedback requests
with file upload support and email notifications.
"""

import logging
import os
import uuid
import math
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status, Depends, Query
from fastapi.responses import JSONResponse
from typing import Optional
from bson import ObjectId

from services.auth.support_feedback_service import get_support_feedback_service
from services.auth.models import SupportFeedbackResponse
from core.utils.response_utils import create_response
from core.auth.auth_middleware import get_current_user_or_admin
from core.database.collections import get_collections

logger = logging.getLogger(__name__)

router = APIRouter()

# Configure upload directory
UPLOAD_DIR = "uploads/support_attachments"
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/support-feedback", response_model=SupportFeedbackResponse)
async def submit_support_feedback(
    first_name: str = Form(..., description="First name of the user"),
    email: str = Form(..., description="Email address of the user"),
    subject: str = Form(..., description="Brief description of the inquiry"),
    message: str = Form(..., description="Detailed message"),
    type: str = Form(..., description="Type of support request: 'club' or 'platform'"),
    selected_club: str = Form(None, description="Club name_based_id if type is 'club'"),
    attachment: UploadFile = File(None, description="Optional file attachment (JPEG or PNG, max 5MB)")
):
    """
    Submit support and feedback request with optional file attachment
    
    **Features:**
    - **Form Data**: Accepts form data with text fields
    - **File Upload**: Optional file attachment support (JPEG/PNG, max 5MB)
    - **Email Notifications**: Sends emails based on type (club vs platform)
    - **Database Storage**: Stores all submissions in support_feedback collection
    - **Validation**: Validates email format and file types
    
    **Form Fields:**
    - **first_name**: User's first name (required, 1-100 characters)
    - **email**: User's email address (required, valid email format)
    - **subject**: Brief description of inquiry (required, 1-200 characters)
    - **message**: Detailed message (required, 1-5000 characters)
    - **type**: Type of support request (required, 'club' or 'platform')
    - **selected_club**: Club name_based_id if type is 'club' (required when type='club')
    - **attachment**: Optional file upload (JPEG/PNG, max 5MB)
    
    **Email Notifications:**
    - **Club Type**: Sends email to club captain and all moderators
    - **Platform Type**: Sends email to all platform admins
    - **User Confirmation**: Always sends confirmation email to user
    
    **Response includes:**
    - Support ID for tracking
    - Submission confirmation
    - Email notification status
    
    **Business Logic:**
    - Stores submission in database with unique ID
    - Routes emails based on type (club vs platform)
    - Sends confirmation email to user
    - Validates file types and sizes
    - Generates unique filenames for attachments
    """
    try:
        logger.info(f"Support feedback submission from: {email}")
        
        # Validate required fields
        if not first_name or not first_name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="First name is required"
            )
        
        if not email or not email.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required"
            )
        
        if not subject or not subject.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subject is required"
            )
        
        if not message or not message.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message is required"
            )
        
        if not type or not type.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Type is required"
            )
        
        # Validate type value
        if type.strip().lower() not in ['club', 'platform']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Type must be either 'club' or 'platform'"
            )
        
        # Validate selected_club if type is 'club'
        if type.strip().lower() == 'club' and (not selected_club or not selected_club.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected club is required when type is 'club'"
            )
        
        # Handle file attachment if provided
        attachment_filename = None
        attachment_path = None
        attachment_url = None
        
        if attachment and attachment.filename:
            try:
                # Validate file size
                content = await attachment.read()
                if len(content) > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File size exceeds maximum limit of {MAX_FILE_SIZE // (1024*1024)}MB"
                    )
                
                # Validate file extension
                file_extension = os.path.splitext(attachment.filename)[1].lower()
                if file_extension not in ALLOWED_EXTENSIONS:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Only JPEG and PNG files are allowed"
                    )
                
                # Generate unique filename
                unique_id = str(uuid.uuid4())
                attachment_filename = f"{unique_id}{file_extension}"
                attachment_path = os.path.join(UPLOAD_DIR, attachment_filename)
                
                # Save file
                with open(attachment_path, "wb") as buffer:
                    buffer.write(content)
                
                # Convert path to full URL for database storage
                base_url = os.getenv("simbet_website_url", "https://api.simbet.websitetestingbox.com/")
                # Normalize path separators for URL (use forward slashes)
                normalized_path = attachment_path.replace("\\", "/")
                attachment_url = f"{base_url}/{normalized_path}"
                
                logger.info(f"File attachment saved: {attachment_path}")
                logger.info(f"Attachment URL: {attachment_url}")
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error handling file attachment: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to process file attachment"
                )
        
        # Submit support feedback
        support_feedback_service = get_support_feedback_service()
        success, data, error_message = await support_feedback_service.submit_support_feedback(
            first_name=first_name.strip(),
            email=email.strip(),
            subject=subject.strip(),
            message=message.strip(),
            type=type.strip().lower(),
            selected_club=selected_club.strip() if selected_club else None,
            attachment_filename=attachment_filename,
            attachment_path=attachment_url  # Pass URL instead of local path
        )
        
        if not success:
            # Clean up uploaded file if submission failed
            if attachment_path and os.path.exists(attachment_path):
                try:
                    os.remove(attachment_path)
                    logger.info(f"Cleaned up file after failed submission: {attachment_path}")
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up file: {cleanup_error}")
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_message or "Failed to submit support feedback"
            )
        
        logger.info(f"Support feedback submitted successfully: {data.get('support_id')}")
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Support request submitted successfully. We'll get back to you soon!",
            data=data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in submit_support_feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        )


async def verify_admin_or_captain(current_user: dict = Depends(get_current_user_or_admin)) -> dict:
    """Verify that the user is either an admin or a captain"""
    user_type = current_user.get("user_type")
    role = current_user.get("role")
    
    # Check if admin
    if user_type == "admin" or role == "admin":
        return {
            **current_user,
            "is_admin": True,
            "is_captain": False
        }
    
    # Check if captain - verify by checking if user owns any clubs
    user_id = current_user.get("user_id")
    if user_id:
        try:
            collections = get_collections()
            clubs_collection = collections.get_clubs_collection()
            
            # Check if user is captain of any club
            captain_clubs = await clubs_collection.find({
                "captain_id": user_id
            }).to_list(length=None)
            
            if len(captain_clubs) > 0:
                # Get all club name_based_ids for this captain
                club_ids = [club.get("name_based_id") for club in captain_clubs if club.get("name_based_id")]
                
                return {
                    **current_user,
                    "is_admin": False,
                    "is_captain": True,
                    "captain_club_ids": club_ids
                }
        except Exception as e:
            logger.error(f"Error verifying captain status: {e}")
    
    # User is neither admin nor captain
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only admins and captains can access this endpoint"
    )


@router.get("/support-feedback")
async def get_support_feedback(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    type: Optional[str] = Query(None, description="Filter by type: 'club' or 'platform'"),
    response_status: Optional[str] = Query(None, description="Filter by response status: 'pending' or 'completed'"),
    search: Optional[str] = Query(None, description="Search by name, email, or subject"),
    current_user: dict = Depends(verify_admin_or_captain)
):
    """
    Get support feedback submissions with pagination and filtering.
    
    **Authorization:**
    - Only admins and captains can access this endpoint
    - Admins can see all feedback based on type filter
    - Captains can only see feedback for their own clubs when type='club'
    - Captains cannot see platform feedback (type='platform')
    
    **Query Parameters:**
    - `page`: Page number (default: 1, min: 1)
    - `limit`: Items per page (default: 20, min: 1, max: 100)
    - `type`: Filter by type - 'club' or 'platform' (optional)
    - `response_status`: Filter by response status - 'pending' or 'completed' (optional)
    - `search`: Search by name, email, or subject (optional, case-insensitive)
    
    **Access Rules:**
    - **Admin**: Can ONLY view platform type tickets
      - `type='platform'`: All platform-related feedback
      - `type='club'`: Not allowed (403 Forbidden)
      - `type=None`: All platform feedback (default)
    
    - **Captain**: Can only see club feedback for clubs they have created
      - `type='club'`: Only feedback for clubs where they are captain (clubs they created)
      - `type='platform'`: Not allowed (403 Forbidden)
      - `type=None`: Only club feedback for their own clubs (default)
    
    **Returns:**
    - Paginated list of support feedback submissions
    - Total count, page info, and pagination metadata
    
    **Search and Filter Examples:**
    - Search by name: `?search=John`
    - Search by email: `?search=john@example.com`
    - Search by subject: `?search=issue`
    - Filter by response status: `?response_status=pending` or `?response_status=completed`
    - Combine filters: `?type=platform&response_status=pending&search=issue&page=1&limit=20`
    
    **Example Response:**
    ```json
    {
        "status": "success",
        "message": "Support feedback retrieved successfully",
        "data": {
            "feedback": [
                {
                    "_id": "support_id_123",
                    "first_name": "John",
                    "email": "john@example.com",
                    "subject": "Issue with club",
                    "message": "Description...",
                    "type": "club",
                    "selected_club": "my-club-id",
                    "status": "new",
                    "response_status": "pending",
                    "priority": "medium",
                    "created_at": "2024-01-15T10:30:00Z",
                    "attachment_filename": "image.jpg"
                }
            ],
            "total": 50,
            "page": 1,
            "limit": 20,
            "total_pages": 3
        }
    }
    ```
    """
    try:
        collections = get_collections()
        support_feedback_collection = collections.get_support_feedback_collection()
        
        is_admin = current_user.get("is_admin", False)
        is_captain = current_user.get("is_captain", False)
        captain_club_ids = current_user.get("captain_club_ids", [])
        
        # Build query based on user type and filters
        query = {}
        
        # Validate type filter
        if type:
            type_lower = type.strip().lower()
            if type_lower not in ['club', 'platform']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Type must be either 'club' or 'platform'"
                )
        
        # Validate and add response_status filter
        if response_status:
            response_status_lower = response_status.strip().lower()
            if response_status_lower not in ['pending', 'completed']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Response status must be either 'pending' or 'completed'"
                )
            query["response_status"] = response_status_lower
        
        # Apply access control based on user type
        if is_admin:
            # Admins can ONLY view platform type tickets
            query["type"] = "platform"
            
            # If type filter is provided and it's not platform, raise error
            if type and type.strip().lower() != 'platform':
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admins can only view platform type tickets"
                )
        
        elif is_captain:
            # Captains can ONLY see club feedback for clubs they have created
            query["type"] = "club"
            
            # Captains cannot access platform feedback
            if type and type.strip().lower() == 'platform':
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Captains cannot access platform feedback"
                )
            
            # Only show feedback for clubs where user is captain (clubs they created)
            if captain_club_ids:
                query["selected_club"] = {"$in": captain_club_ids}
            else:
                # Captain has no clubs, return empty result
                query["selected_club"] = {"$exists": False}  # This will return 0 results
        
        # Add search functionality (search by name, email, or subject)
        # Combine search with existing query using $and if needed
        if search:
            search_term = search.strip()
            if search_term:
                # Case-insensitive regex search for name, email, or subject
                search_condition = {
                    "$or": [
                        {"first_name": {"$regex": search_term, "$options": "i"}},
                        {"email": {"$regex": search_term, "$options": "i"}},
                        {"subject": {"$regex": search_term, "$options": "i"}}
                    ]
                }
                
                # If query already has conditions, combine using $and
                if query:
                    # Create a new query with $and to combine existing conditions with search
                    query = {
                        "$and": [
                            query,
                            search_condition
                        ]
                    }
                else:
                    # If query is empty, just use search condition
                    query = search_condition
        
        # Calculate pagination
        skip = (page - 1) * limit
        
        # Get total count
        total_count = await support_feedback_collection.count_documents(query)
        
        # Get feedback with pagination (sorted by created_at descending - newest first)
        feedback_cursor = support_feedback_collection.find(query)
        feedback_cursor = feedback_cursor.sort("created_at", -1).skip(skip).limit(limit)
        feedback_list = await feedback_cursor.to_list(length=limit)
        
        # Convert ObjectId to string and format dates
        formatted_feedback = []
        for item in feedback_list:
            # Get response_status (default to "pending" if not present for backward compatibility)
            response_status = item.get("response_status", "pending")
            
            # Get response data if exists
            response = item.get("response")
            formatted_response = None
            if response:
                formatted_response = {
                    "reply_message": response.get("reply_message"),
                    "responded_by": response.get("responded_by"),
                    "responded_by_type": response.get("responded_by_type"),
                    "responded_at": response.get("responded_at").isoformat() if response.get("responded_at") else None,
                    "attachment_filename": response.get("attachment_filename"),
                    "attachment_path": response.get("attachment_path")
                }
            
            formatted_item = {
                "_id": str(item["_id"]),
                "first_name": item.get("first_name"),
                "email": item.get("email"),
                "subject": item.get("subject"),
                "message": item.get("message"),
                "type": item.get("type"),
                "selected_club": item.get("selected_club"),
                "status": item.get("status"),
                "response_status": response_status,  # Can be returned as-is or formatted (stored in lowercase)
                "priority": item.get("priority"),
                "attachment_filename": item.get("attachment_filename"),
                "attachment_path": item.get("attachment_path"),
                "response": formatted_response,  # Response from admin/captain if exists
                "created_at": item.get("created_at").isoformat() if item.get("created_at") else None,
                "updated_at": item.get("updated_at").isoformat() if item.get("updated_at") else None
            }
            formatted_feedback.append(formatted_item)
        
        # Calculate total pages
        total_pages = math.ceil(total_count / limit) if limit > 0 else 0
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Support feedback retrieved successfully",
            data={
                "feedback": formatted_feedback,
                "total": total_count,
                "page": page,
                "limit": limit,
                "skip": skip,
                "total_pages": total_pages
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving support feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve support feedback: {str(e)}"
        )


@router.put("/support-feedback/{support_id}/respond")
async def respond_to_support_ticket(
    support_id: str,
    reply_message: str = Form(..., description="Response message (required)"),
    attachment: str = Form(None, description="Optional attachment URL"),
    current_user: dict = Depends(verify_admin_or_captain)
):
    """
    Respond to a support feedback ticket.
    
    **Authorization:**
    - Only admins and captains can respond to tickets
    - Admins can only respond to platform type tickets
    - Captains can only respond to club type tickets for their own clubs
    
    **Path Parameters:**
    - `support_id`: Support feedback ID (e.g., "690996f6666a3972442bccd1")
    
    **Form Fields:**
    - `reply_message`: Response message (required)
    - `attachment`: Optional attachment URL (must be a valid URL starting with http:// or https://)
    
    **Access Rules:**
    - **Admin**: Can only respond to platform type tickets
      - If ticket type is "club", returns 403 Forbidden
    
    - **Captain**: Can only respond to club type tickets for their own clubs
      - If ticket type is "platform", returns 403 Forbidden
      - If ticket is for a club they don't own, returns 403 Forbidden
    
    **Actions:**
    - Updates the support ticket with response
    - Changes `response_status` from "pending" to "completed"
    - Stores response message, responder info, and optional attachment
    - Sends email notification to the original submitter
    
    **Returns:**
    - Success message with response details
    - Email notification status
    
    **Example Response:**
    ```json
    {
        "status": "success",
        "message": "Response submitted successfully",
        "data": {
            "support_id": "690996f6666a3972442bccd1",
            "reply_message": "Thank you for your inquiry...",
            "responded_by": "admin@example.com",
            "responded_by_type": "admin",
            "response_status": "completed",
            "responded_at": "2024-01-15T10:30:00Z",
            "attachment_filename": "response.jpg",
            "email_sent": true
        }
    }
    ```
    """
    try:
        logger.info(f"Support feedback response submission for ID: {support_id} by {current_user.get('email', 'unknown')}")
        
        # Validate reply_message
        if not reply_message or not reply_message.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reply message is required"
            )
        
        # Validate support ID format
        if not ObjectId.is_valid(support_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid support feedback ID format"
            )
        
        # Get support feedback to check permissions
        collections = get_collections()
        support_feedback_collection = collections.get_support_feedback_collection()
        
        support_record = await support_feedback_collection.find_one({
            "_id": ObjectId(support_id)
        })
        
        if not support_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Support feedback not found"
            )
        
        # Validate permissions based on user type and ticket type
        is_admin = current_user.get("is_admin", False)
        is_captain = current_user.get("is_captain", False)
        captain_club_ids = current_user.get("captain_club_ids", [])
        feedback_type = support_record.get("type")
        selected_club = support_record.get("selected_club")
        
        if is_admin:
            # Admin can only respond to platform type tickets
            if feedback_type != "platform":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admins can only respond to platform type tickets"
                )
            responded_by = current_user.get("email", current_user.get("user_id", "unknown"))
            responded_by_type = "admin"
        
        elif is_captain:
            # Captain can only respond to club type tickets for their own clubs
            if feedback_type != "club":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Captains can only respond to club type tickets"
                )
            
            # Verify captain owns the club
            if selected_club not in captain_club_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only respond to tickets for clubs you have created"
                )
            
            responded_by = current_user.get("email", current_user.get("user_id", "unknown"))
            responded_by_type = "captain"
        
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and captains can respond to support tickets"
            )
        
        # Handle attachment URL if provided
        attachment_filename = None
        attachment_url = None
        
        if attachment and attachment.strip():
            # Validate URL format (basic validation)
            attachment_url = attachment.strip()
            if not attachment_url.startswith(('http://', 'https://')):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Attachment must be a valid URL (starting with http:// or https://)"
                )
            # Extract filename from URL if possible
            attachment_filename = os.path.basename(attachment_url.split('?')[0])  # Remove query params
            logger.info(f"Response attachment URL: {attachment_url}")
        
        # Submit response
        support_feedback_service = get_support_feedback_service()
        success, data, error_message = await support_feedback_service.respond_to_support_feedback(
            support_id=support_id,
            reply_message=reply_message.strip(),
            responded_by=responded_by,
            responded_by_type=responded_by_type,
            attachment_filename=attachment_filename,
            attachment_path=attachment_url  # Pass URL instead of local path
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_message or "Failed to submit response"
            )
        
        logger.info(f"Support feedback response submitted successfully for ID: {support_id}")
        
        return create_response(
            status_code=status.HTTP_200_OK,
            status="success",
            message="Response submitted successfully. Email notification sent to the original submitter.",
            data=data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in respond_to_support_ticket: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred"
        )


