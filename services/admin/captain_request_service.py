#!/usr/bin/env python3
"""
Captain Request Management Service

This service handles the complete workflow for Captain moderator requests:
- Captain submits requests for moderator actions
- Admin reviews and approves/rejects requests
- Provides request_id for moderator CRUD operations

Key Features:
- Request ID Generation
- Captain Request Submission
- Admin Approval/Rejection
- Request Status Tracking
- Complete Audit Trail
"""

import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple
from bson import ObjectId

from .models import (
    CaptainModeratorRequestSubmission, CaptainRequestSubmissionResponse,
    AdminRequestApprovalRequest, AdminRequestApprovalResponse,
    CaptainRequestListRequest, CaptainRequestListResponse,
    CaptainRequestData, CaptainRequestListPagination,
    ModeratorRequestStatus, ModeratorActionType
)
from .db import (
    users_collection, clubs_collection, moderator_requests_collection,
    moderator_audit_logs_collection
)

class AdminCaptainRequestService:
    """
    Service for managing Captain moderator requests and admin approvals
    """
    
    def __init__(self):
        self.service_name = "AdminCaptainRequestService"
    
    async def submit_captain_request(self, request: CaptainModeratorRequestSubmission, 
                                   captain_id: str, captain_email: str) -> CaptainRequestSubmissionResponse:
        """
        Submit a new Captain request for moderator action
        
        Args:
            request: Captain request submission data
            captain_id: ID of the captain submitting the request
            captain_email: Email of the captain submitting the request
        
        Returns:
            CaptainRequestSubmissionResponse with request_id
        """
        try:
            print(f"📝 Captain {captain_email} submitting {request.action_type.value} request")
            
            # Step 1: Validate captain exists and has access to club
            captain_validation = await self._validate_captain_access(captain_id, request.club_id)
            if not captain_validation["is_valid"]:
                return CaptainRequestSubmissionResponse(
                    success=False,
                    message=captain_validation["error"],
                    request_id="INVALID"
                )
            
            # Step 2: Validate moderator for edit/delete actions
            if request.moderator_id:
                moderator_validation = await self._validate_moderator_exists(request.moderator_id)
                if not moderator_validation["exists"]:
                    return CaptainRequestSubmissionResponse(
                        success=False,
                        message=f"Moderator with ID {request.moderator_id} not found",
                        request_id="INVALID"
                    )
            
            # Step 3: Generate unique request ID
            request_id = self._generate_request_id(request.action_type, captain_id)
            
            # Step 4: Create request document
            request_doc = {
                "_id": ObjectId(),
                "request_id": request_id,
                "action_type": request.action_type.value,
                "moderator_id": request.moderator_id,
                "moderator_data": request.moderator_data,
                "request_reason": request.request_reason,
                "request_status": ModeratorRequestStatus.PENDING.value,
                "requested_by_captain_id": captain_id,
                "captain_name": captain_validation["captain_name"],
                "club_id": request.club_id,
                "request_timestamp": datetime.now(timezone.utc),
                "approved_by_admin_id": None,
                "approval_timestamp": None,
                "rejection_reason": None,
                "admin_notes": None
            }
            
            # Step 5: Insert request into database
            await moderator_requests_collection.insert_one(request_doc)
            
            # Step 6: Get club name for response
            club = await clubs_collection.find_one({"_id": ObjectId(request.club_id)})
            club_name = club["name"] if club else "Unknown Club"
            
            # Step 7: Format response data
            request_data = CaptainRequestData(
                request_id=request_id,
                action_type=request.action_type.value,
                moderator_id=request.moderator_id,
                moderator_data=request.moderator_data,
                request_reason=request.request_reason,
                request_status=ModeratorRequestStatus.PENDING.value,
                requested_by_captain_id=captain_id,
                captain_name=captain_validation["captain_name"],
                club_id=request.club_id,
                club_name=club_name,
                request_timestamp=request_doc["request_timestamp"].strftime("%d %b %Y %H:%M"),
                approved_by_admin_id=None,
                approved_by_admin_name=None,
                approval_timestamp=None,
                rejection_reason=None
            )
            
            print(f"✅ Captain request submitted successfully: {request_id}")
            
            return CaptainRequestSubmissionResponse(
                success=True,
                message=f"Moderator {request.action_type.value} request submitted successfully",
                request=request_data,
                request_id=request_id
            )
            
        except Exception as e:
            error_msg = f"Failed to submit captain request: {str(e)}"
            print(f"❌ Error submitting captain request: {e}")
            
            return CaptainRequestSubmissionResponse(
                success=False,
                message=error_msg,
                request_id="ERROR"
            )
    
    async def approve_reject_request(self, request_id: str, approval_request: AdminRequestApprovalRequest,
                                   admin_id: str, admin_email: str) -> AdminRequestApprovalResponse:
        """
        Approve or reject a Captain request
        
        Args:
            request_id: ID of the request to approve/reject
            approval_request: Admin approval/rejection data
            admin_id: ID of the admin making the decision
            admin_email: Email of the admin making the decision
        
        Returns:
            AdminRequestApprovalResponse with updated request data
        """
        try:
            print(f"⚖️ Admin {admin_email} {approval_request.action}ing request {request_id}")
            
            # Step 1: Find and validate request
            request_doc = await moderator_requests_collection.find_one({
                "request_id": request_id
            })
            
            if not request_doc:
                return AdminRequestApprovalResponse(
                    success=False,
                    message=f"Request with ID {request_id} not found",
                    action_taken="none"
                )
            
            if request_doc["request_status"] != ModeratorRequestStatus.PENDING.value:
                return AdminRequestApprovalResponse(
                    success=False,
                    message=f"Request {request_id} has already been {request_doc['request_status']}",
                    action_taken="none"
                )
            
            # Step 2: Update request status
            now = datetime.now(timezone.utc)
            new_status = ModeratorRequestStatus.APPROVED.value if approval_request.action == "approve" else ModeratorRequestStatus.REJECTED.value
            
            update_data = {
                "request_status": new_status,
                "approved_by_admin_id": admin_id,
                "approval_timestamp": now,
                "admin_notes": approval_request.admin_notes
            }
            
            if approval_request.action == "reject":
                update_data["rejection_reason"] = approval_request.rejection_reason
            
            # Step 3: Update request in database
            await moderator_requests_collection.update_one(
                {"request_id": request_id},
                {"$set": update_data}
            )
            
            # Step 4: Get updated request data
            updated_request = await moderator_requests_collection.find_one({
                "request_id": request_id
            })
            
            # Step 5: Get admin and club names
            admin_name = await self._get_admin_name(admin_id)
            club = await clubs_collection.find_one({"_id": ObjectId(updated_request["club_id"])})
            club_name = club["name"] if club else "Unknown Club"
            
            # Step 6: Format response data
            request_data = CaptainRequestData(
                request_id=request_id,
                action_type=updated_request["action_type"],
                moderator_id=updated_request["moderator_id"],
                moderator_data=updated_request["moderator_data"],
                request_reason=updated_request["request_reason"],
                request_status=new_status,
                requested_by_captain_id=updated_request["requested_by_captain_id"],
                captain_name=updated_request["captain_name"],
                club_id=updated_request["club_id"],
                club_name=club_name,
                request_timestamp=updated_request["request_timestamp"].strftime("%d %b %Y %H:%M"),
                approved_by_admin_id=admin_id,
                approved_by_admin_name=admin_name,
                approval_timestamp=now.strftime("%d %b %Y %H:%M"),
                rejection_reason=approval_request.rejection_reason if approval_request.action == "reject" else None
            )
            
            action_verb = "approved" if approval_request.action == "approve" else "rejected"
            message = f"Request {request_id} has been {action_verb} successfully"
            
            print(f"✅ Request {action_verb}: {request_id}")
            
            return AdminRequestApprovalResponse(
                success=True,
                message=message,
                request=request_data,
                action_taken=approval_request.action
            )
            
        except Exception as e:
            error_msg = f"Failed to {approval_request.action} request: {str(e)}"
            print(f"❌ Error {approval_request.action}ing request: {e}")
            
            return AdminRequestApprovalResponse(
                success=False,
                message=error_msg,
                action_taken="error"
            )
    
    async def get_requests_list(self, request: CaptainRequestListRequest, 
                              admin_email: str) -> CaptainRequestListResponse:
        """
        Get list of Captain requests with filtering and pagination
        
        Args:
            request: List request with filters and pagination
            admin_email: Email of admin requesting the list
        
        Returns:
            CaptainRequestListResponse with paginated requests
        """
        try:
            print(f"📋 Admin {admin_email} requesting requests list")
            
            # Step 1: Build aggregation pipeline
            pipeline = await self._build_requests_aggregation_pipeline(request)
            
            # Step 2: Get total count
            count_pipeline = pipeline + [{"$count": "total"}]
            count_result = await moderator_requests_collection.aggregate(count_pipeline).to_list(length=1)
            total_records = count_result[0]["total"] if count_result else 0
            
            # Step 3: Apply pagination
            skip = (request.page - 1) * request.limit
            paginated_pipeline = pipeline + [
                {"$skip": skip},
                {"$limit": request.limit}
            ]
            
            # Step 4: Execute query
            requests_cursor = moderator_requests_collection.aggregate(paginated_pipeline)
            requests_docs = await requests_cursor.to_list(length=None)
            
            # Step 5: Format response data
            requests_list = []
            for doc in requests_docs:
                request_data = CaptainRequestData(
                    request_id=doc["request_id"],
                    action_type=doc["action_type"],
                    moderator_id=doc.get("moderator_id"),
                    moderator_data=doc.get("moderator_data"),
                    request_reason=doc["request_reason"],
                    request_status=doc["request_status"],
                    requested_by_captain_id=doc["requested_by_captain_id"],
                    captain_name=doc["captain_name"],
                    club_id=doc["club_id"],
                    club_name=doc.get("club_name", "Unknown Club"),
                    request_timestamp=doc["request_timestamp"].strftime("%d %b %Y %H:%M"),
                    approved_by_admin_id=doc.get("approved_by_admin_id"),
                    approved_by_admin_name=doc.get("approved_by_admin_name"),
                    approval_timestamp=doc.get("approval_timestamp").strftime("%d %b %Y %H:%M") if doc.get("approval_timestamp") else None,
                    rejection_reason=doc.get("rejection_reason")
                )
                requests_list.append(request_data)
            
            # Step 6: Calculate pagination
            total_pages = (total_records + request.limit - 1) // request.limit
            pagination = CaptainRequestListPagination(
                current_page=request.page,
                total_pages=total_pages,
                total_records=total_records,
                records_per_page=request.limit,
                has_next=request.page < total_pages,
                has_previous=request.page > 1
            )
            
            # Step 7: Get status counts
            status_counts = await self._get_status_counts(request)
            
            # Step 8: Get applied filters
            filters_applied = self._get_applied_filters(request)
            
            print(f"✅ Retrieved {len(requests_list)} requests from {total_records} total")
            
            return CaptainRequestListResponse(
                success=True,
                message=f"Retrieved {len(requests_list)} requests successfully",
                requests=requests_list,
                pagination=pagination,
                filters_applied=filters_applied,
                total_pending=status_counts["pending"],
                total_approved=status_counts["approved"],
                total_rejected=status_counts["rejected"]
            )
            
        except Exception as e:
            error_msg = f"Failed to retrieve requests list: {str(e)}"
            print(f"❌ Error retrieving requests list: {e}")
            
            return CaptainRequestListResponse(
                success=False,
                message=error_msg,
                requests=[],
                pagination=CaptainRequestListPagination(
                    current_page=1, total_pages=0, total_records=0,
                    records_per_page=request.limit, has_next=False, has_previous=False
                ),
                filters_applied={},
                total_pending=0,
                total_approved=0,
                total_rejected=0
            )
    
    # ========================================
    # Private Helper Methods
    # ========================================
    
    def _generate_request_id(self, action_type: ModeratorActionType, captain_id: str) -> str:
        """
        Generate a unique request ID
        
        Args:
            action_type: Type of action being requested
            captain_id: ID of the captain making the request
        
        Returns:
            Unique request ID string
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        action_prefix = action_type.value.upper()
        captain_suffix = captain_id[-4:] if len(captain_id) >= 4 else captain_id
        unique_suffix = uuid.uuid4().hex[:6].upper()
        
        return f"REQ_{action_prefix}_{timestamp}_{captain_suffix}_{unique_suffix}"
    
    async def _validate_captain_access(self, captain_id: str, club_id: str) -> Dict[str, Any]:
        """
        Validate that captain exists and has access to the club
        
        Args:
            captain_id: ID of the captain
            club_id: ID of the club
        
        Returns:
            Dict with validation result and captain details
        """
        try:
            # Check if captain exists
            captain = await users_collection.find_one({
                "_id": ObjectId(captain_id),
                "role": "captain",
                "is_active": True,
                "is_deleted": False
            })
            
            if not captain:
                return {
                    "is_valid": False,
                    "error": f"Captain with ID {captain_id} not found or inactive",
                    "captain_name": "Unknown"
                }
            
            # Check if captain has access to club
            club = await clubs_collection.find_one({
                "_id": ObjectId(club_id),
                "captain_id": ObjectId(captain_id),
                "is_deleted": {"$ne": True}
            })
            
            if not club:
                return {
                    "is_valid": False,
                    "error": f"Captain does not have access to club {club_id}",
                    "captain_name": captain.get("full_name", "Unknown")
                }
            
            return {
                "is_valid": True,
                "error": None,
                "captain_name": captain.get("full_name", "Unknown"),
                "club_name": club.get("name", "Unknown Club")
            }
            
        except Exception as e:
            print(f"❌ Error validating captain access: {e}")
            return {
                "is_valid": False,
                "error": f"Failed to validate captain access: {str(e)}",
                "captain_name": "Unknown"
            }
    
    async def _validate_moderator_exists(self, moderator_id: str) -> Dict[str, Any]:
        """
        Validate that moderator exists and is not deleted
        
        Args:
            moderator_id: ID of the moderator
        
        Returns:
            Dict with validation result
        """
        try:
            moderator = await users_collection.find_one({
                "_id": ObjectId(moderator_id),
                "role": "moderator",
                "is_deleted": False
            })
            
            return {
                "exists": moderator is not None,
                "moderator_name": moderator.get("full_name", "Unknown") if moderator else None
            }
            
        except Exception as e:
            print(f"❌ Error validating moderator: {e}")
            return {"exists": False, "moderator_name": None}
    
    async def _get_admin_name(self, admin_id: str) -> str:
        """
        Get admin name by ID
        
        Args:
            admin_id: Admin user ID
        
        Returns:
            Admin name or "Unknown"
        """
        try:
            if not admin_id:
                return "Unknown"
            
            admin = await users_collection.find_one({"_id": ObjectId(admin_id)})
            return admin.get("full_name", "Unknown") if admin else "Unknown"
            
        except Exception as e:
            print(f"❌ Error getting admin name: {e}")
            return "Unknown"
    
    async def _build_requests_aggregation_pipeline(self, request: CaptainRequestListRequest) -> List[Dict[str, Any]]:
        """
        Build MongoDB aggregation pipeline for requests list
        
        Args:
            request: List request with filters
        
        Returns:
            Aggregation pipeline stages
        """
        pipeline = []
        
        # Stage 1: Basic filtering
        match_stage = {}
        
        if request.status:
            match_stage["request_status"] = request.status.value
        
        if request.action_type:
            match_stage["action_type"] = request.action_type.value
        
        if request.captain_id:
            match_stage["requested_by_captain_id"] = request.captain_id
        
        if request.club_id:
            match_stage["club_id"] = request.club_id
        
        # Date filtering
        if request.date_from or request.date_to:
            date_filter = {}
            if request.date_from:
                date_from = datetime.strptime(request.date_from, "%Y-%m-%d")
                date_filter["$gte"] = date_from
            if request.date_to:
                date_to = datetime.strptime(request.date_to, "%Y-%m-%d") + timedelta(days=1)
                date_filter["$lt"] = date_to
            
            if date_filter:
                match_stage["request_timestamp"] = date_filter
        
        if match_stage:
            pipeline.append({"$match": match_stage})
        
        # Stage 2: Lookup club details
        pipeline.append({
            "$lookup": {
                "from": "clubs",
                "localField": "club_id",
                "foreignField": "_id",
                "as": "club_data"
            }
        })
        
        # Stage 3: Add club name
        pipeline.append({
            "$addFields": {
                "club_name": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$club_data.name", 0]},
                        "Unknown Club"
                    ]
                }
            }
        })
        
        # Stage 4: Lookup admin details (for approved/rejected requests)
        pipeline.append({
            "$lookup": {
                "from": "users",
                "localField": "approved_by_admin_id",
                "foreignField": "_id",
                "as": "admin_data"
            }
        })
        
        # Stage 5: Add admin name
        pipeline.append({
            "$addFields": {
                "approved_by_admin_name": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$admin_data.full_name", 0]},
                        None
                    ]
                }
            }
        })
        
        # Stage 6: Sort by request timestamp (newest first)
        pipeline.append({
            "$sort": {"request_timestamp": -1}
        })
        
        return pipeline
    
    async def _get_status_counts(self, request: CaptainRequestListRequest) -> Dict[str, int]:
        """
        Get count of requests by status
        
        Args:
            request: List request for filtering context
        
        Returns:
            Dict with status counts
        """
        try:
            # Build basic filter (excluding status filter)
            match_stage = {}
            
            if request.action_type:
                match_stage["action_type"] = request.action_type.value
            
            if request.captain_id:
                match_stage["requested_by_captain_id"] = request.captain_id
            
            if request.club_id:
                match_stage["club_id"] = request.club_id
            
            # Date filtering
            if request.date_from or request.date_to:
                date_filter = {}
                if request.date_from:
                    date_from = datetime.strptime(request.date_from, "%Y-%m-%d")
                    date_filter["$gte"] = date_from
                if request.date_to:
                    date_to = datetime.strptime(request.date_to, "%Y-%m-%d") + timedelta(days=1)
                    date_filter["$lt"] = date_to
                
                if date_filter:
                    match_stage["request_timestamp"] = date_filter
            
            # Count by status
            pipeline = []
            if match_stage:
                pipeline.append({"$match": match_stage})
            
            pipeline.append({
                "$group": {
                    "_id": "$request_status",
                    "count": {"$sum": 1}
                }
            })
            
            result = await moderator_requests_collection.aggregate(pipeline).to_list(length=None)
            
            counts = {"pending": 0, "approved": 0, "rejected": 0}
            for item in result:
                if item["_id"] in counts:
                    counts[item["_id"]] = item["count"]
            
            return counts
            
        except Exception as e:
            print(f"❌ Error getting status counts: {e}")
            return {"pending": 0, "approved": 0, "rejected": 0}
    
    def _get_applied_filters(self, request: CaptainRequestListRequest) -> Dict[str, Any]:
        """
        Get dictionary of applied filters for response
        
        Args:
            request: List request with filters
        
        Returns:
            Dict of applied filters
        """
        filters = {}
        
        if request.status:
            filters["status"] = request.status.value
        if request.action_type:
            filters["action_type"] = request.action_type.value
        if request.captain_id:
            filters["captain_id"] = request.captain_id
        if request.club_id:
            filters["club_id"] = request.club_id
        if request.date_from:
            filters["date_from"] = request.date_from
        if request.date_to:
            filters["date_to"] = request.date_to
        
        filters["page"] = request.page
        filters["limit"] = request.limit
        
        return filters

# Create service instance
admin_captain_request_service = AdminCaptainRequestService()