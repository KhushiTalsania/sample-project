#!/usr/bin/env python3
"""
Moderator Management Service with Captain Request Approval

This service handles CRUD operations for moderators with mandatory Captain approval.
All actions require an approved Captain request and include comprehensive audit logging.

Key Features:
- Captain Request Validation
- Atomic Operations
- Comprehensive Audit Logging
- Email Uniqueness Validation
- Club and Role Assignment
- Error Handling and Security
"""

import uuid
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from bson import ObjectId

from .models import (
    ModeratorCreateRequest, ModeratorUpdateRequest, ModeratorDeleteRequest,
    ModeratorCreateResponse, ModeratorUpdateResponse, ModeratorDeleteResponse,
    ModeratorData, ModeratorAuditLogEntry, ModeratorRequest,
    ModeratorActionType, ModeratorRequestStatus, ModeratorRoleType
)
from .db import (
    users_collection, club_memberships_collection, clubs_collection,
    moderator_requests_collection, moderator_audit_logs_collection
)

class AdminModeratorManagementService:
    """
    Service for managing moderators with Captain request approval dependency
    """
    
    def __init__(self):
        self.service_name = "AdminModeratorManagementService"
    
    async def create_moderator(self, request: ModeratorCreateRequest, admin_email: str, 
                             admin_id: str) -> ModeratorCreateResponse:
        """
        Create a new moderator with Captain approval validation
        
        Args:
            request: Moderator creation request with approved Captain request ID
            admin_email: Email of admin performing the action
            admin_id: ID of admin performing the action
        
        Returns:
            ModeratorCreateResponse with success status and created moderator data
        """
        try:
            print(f"🚀 Creating moderator with request ID: {request.request_id}")
            
            # Step 1: Validate Captain request
            captain_request = await self._validate_captain_request(
                request.request_id, ModeratorActionType.ADD
            )
            
            if not captain_request["is_valid"]:
                return ModeratorCreateResponse(
                    success=False,
                    message=captain_request["error"],
                    request_id=request.request_id,
                    action_logged=await self._log_action_result(
                        ModeratorActionType.ADD, None, admin_id, admin_email,
                        captain_request["captain_id"], captain_request["captain_name"],
                        captain_request["club_id"], request.request_id,
                        captain_request["reason"], "denied", captain_request["error"]
                    )
                )
            
            # Step 2: Validate email uniqueness
            email_check = await self._check_email_uniqueness(request.email)
            if not email_check["is_unique"]:
                error_msg = f"Email {request.email} is already in use by another moderator"
                return ModeratorCreateResponse(
                    success=False,
                    message=error_msg,
                    request_id=request.request_id,
                    action_logged=await self._log_action_result(
                        ModeratorActionType.ADD, None, admin_id, admin_email,
                        captain_request["captain_id"], captain_request["captain_name"],
                        captain_request["club_id"], request.request_id,
                        captain_request["reason"], "denied", error_msg
                    )
                )
            
            # Step 3: Validate clubs exist
            clubs_validation = await self._validate_clubs_exist(request.assigned_clubs)
            if not clubs_validation["all_exist"]:
                error_msg = f"Invalid club IDs: {clubs_validation['invalid_clubs']}"
                return ModeratorCreateResponse(
                    success=False,
                    message=error_msg,
                    request_id=request.request_id,
                    action_logged=await self._log_action_result(
                        ModeratorActionType.ADD, None, admin_id, admin_email,
                        captain_request["captain_id"], captain_request["captain_name"],
                        captain_request["club_id"], request.request_id,
                        captain_request["reason"], "denied", error_msg
                    )
                )
            
            # Step 4: Create user document
            moderator_id = str(ObjectId())
            user_doc = {
                "_id": ObjectId(moderator_id),
                "full_name": request.moderator_name,
                "email": request.email.lower(),
                "phone": request.phone,
                "role": "moderator",
                "is_active": True,
                "is_verified": True,
                "is_deleted": False,
                "created_timestamp": datetime.now(timezone.utc),
                "created_by_admin_id": admin_id,
                "last_updated_timestamp": datetime.now(timezone.utc),
                "moderator_roles": [role.value for role in request.roles]
            }
            
            # Step 5: Create club membership documents
            membership_docs = []
            for club_id in request.assigned_clubs:
                membership_doc = {
                    "_id": ObjectId(),
                    "user_id": ObjectId(moderator_id),
                    "club_id": ObjectId(club_id),
                    "role": "moderator",
                    "joined_date": datetime.now(timezone.utc),
                    "is_active": True,
                    "assigned_by_admin_id": admin_id,
                    "request_id": request.request_id,
                    "subscription_status": "active"
                }
                membership_docs.append(membership_doc)
            
            # Step 6: Insert user and memberships
            await users_collection.insert_one(user_doc)
            if membership_docs:
                await club_memberships_collection.insert_many(membership_docs)
            
            # Step 7: Get admin name for response
            admin_name = await self._get_admin_name(admin_id)
            
            # Step 8: Format response data
            moderator_data = ModeratorData(
                moderator_id=moderator_id,
                moderator_name=request.moderator_name,
                email=request.email,
                phone=request.phone,
                assigned_clubs=[
                    {"club_id": club_id, "club_name": clubs_validation["clubs"][club_id]}
                    for club_id in request.assigned_clubs
                ],
                roles=[role.value for role in request.roles],
                is_active=True,
                created_by_admin_id=admin_id,
                created_by_admin_name=admin_name,
                created_timestamp=user_doc["created_timestamp"].strftime("%d %b %Y %H:%M"),
                last_updated_timestamp=None
            )
            
            # Step 9: Log successful action
            changes_made = [
                f"Created moderator: {request.moderator_name}",
                f"Email: {request.email}",
                f"Roles: {[role.value for role in request.roles]}",
                f"Clubs assigned: {len(request.assigned_clubs)}"
            ]
            
            action_logged = await self._log_action_result(
                ModeratorActionType.ADD, moderator_id, admin_id, admin_email,
                captain_request["captain_id"], captain_request["captain_name"],
                captain_request["club_id"], request.request_id,
                captain_request["reason"], "success", None, changes_made
            )
            
            print(f"✅ Moderator created successfully: {moderator_id}")
            
            return ModeratorCreateResponse(
                success=True,
                message=f"Moderator {request.moderator_name} created successfully",
                moderator=moderator_data,
                request_id=request.request_id,
                action_logged=action_logged
            )
            
        except Exception as e:
            error_msg = f"Failed to create moderator: {str(e)}"
            print(f"❌ Error creating moderator: {e}")
            
            # Log failed action
            action_logged = await self._log_action_result(
                ModeratorActionType.ADD, None, admin_id, admin_email,
                "unknown", "unknown", "unknown", request.request_id,
                "moderator creation", "denied", error_msg
            )
            
            return ModeratorCreateResponse(
                success=False,
                message=error_msg,
                request_id=request.request_id,
                action_logged=action_logged
            )
    
    async def update_moderator(self, moderator_id: str, request: ModeratorUpdateRequest, 
                             admin_email: str, admin_id: str) -> ModeratorUpdateResponse:
        """
        Update an existing moderator with Captain approval validation
        
        Args:
            moderator_id: ID of moderator to update
            request: Moderator update request with approved Captain request ID
            admin_email: Email of admin performing the action
            admin_id: ID of admin performing the action
        
        Returns:
            ModeratorUpdateResponse with success status and updated moderator data
        """
        try:
            print(f"🔄 Updating moderator {moderator_id} with request ID: {request.request_id}")
            
            # Step 1: Validate moderator exists
            moderator = await users_collection.find_one({
                "_id": ObjectId(moderator_id),
                "role": "moderator",
                "is_deleted": False
            })
            
            if not moderator:
                error_msg = f"Moderator with ID {moderator_id} not found"
                return ModeratorUpdateResponse(
                    success=False,
                    message=error_msg,
                    request_id=request.request_id,
                    action_logged=await self._log_action_result(
                        ModeratorActionType.EDIT, moderator_id, admin_id, admin_email,
                        "unknown", "unknown", "unknown", request.request_id,
                        "moderator update", "denied", error_msg
                    ),
                    changes_made=[]
                )
            
            # Step 2: Validate Captain request
            captain_request = await self._validate_captain_request(
                request.request_id, ModeratorActionType.EDIT, moderator_id
            )
            
            if not captain_request["is_valid"]:
                return ModeratorUpdateResponse(
                    success=False,
                    message=captain_request["error"],
                    request_id=request.request_id,
                    action_logged=await self._log_action_result(
                        ModeratorActionType.EDIT, moderator_id, admin_id, admin_email,
                        captain_request["captain_id"], captain_request["captain_name"],
                        captain_request["club_id"], request.request_id,
                        captain_request["reason"], "denied", captain_request["error"]
                    ),
                    changes_made=[]
                )
            
            # Step 3: Build update operations
            user_updates = {}
            changes_made = []
            
            if request.moderator_name:
                user_updates["full_name"] = request.moderator_name
                changes_made.append(f"Name: {moderator['full_name']} → {request.moderator_name}")
            
            if request.email:
                # Check email uniqueness (excluding current moderator)
                email_check = await self._check_email_uniqueness(request.email, moderator_id)
                if not email_check["is_unique"]:
                    error_msg = f"Email {request.email} is already in use by another moderator"
                    return ModeratorUpdateResponse(
                        success=False,
                        message=error_msg,
                        request_id=request.request_id,
                        action_logged=await self._log_action_result(
                            ModeratorActionType.EDIT, moderator_id, admin_id, admin_email,
                            captain_request["captain_id"], captain_request["captain_name"],
                            captain_request["club_id"], request.request_id,
                            captain_request["reason"], "denied", error_msg
                        ),
                        changes_made=[]
                    )
                
                user_updates["email"] = request.email.lower()
                changes_made.append(f"Email: {moderator['email']} → {request.email}")
            
            if request.phone is not None:
                user_updates["phone"] = request.phone
                old_phone = moderator.get("phone", "None")
                new_phone = request.phone if request.phone else "None"
                changes_made.append(f"Phone: {old_phone} → {new_phone}")
            
            if request.roles:
                user_updates["moderator_roles"] = [role.value for role in request.roles]
                old_roles = moderator.get("moderator_roles", [])
                new_roles = [role.value for role in request.roles]
                changes_made.append(f"Roles: {old_roles} → {new_roles}")
            
            # Step 4: Handle club assignments
            if request.assigned_clubs is not None:
                # Validate clubs exist
                clubs_validation = await self._validate_clubs_exist(request.assigned_clubs)
                if not clubs_validation["all_exist"]:
                    error_msg = f"Invalid club IDs: {clubs_validation['invalid_clubs']}"
                    return ModeratorUpdateResponse(
                        success=False,
                        message=error_msg,
                        request_id=request.request_id,
                        action_logged=await self._log_action_result(
                            ModeratorActionType.EDIT, moderator_id, admin_id, admin_email,
                            captain_request["captain_id"], captain_request["captain_name"],
                            captain_request["club_id"], request.request_id,
                            captain_request["reason"], "denied", error_msg
                        ),
                        changes_made=[]
                    )
                
                # Remove existing memberships
                await club_memberships_collection.delete_many({
                    "user_id": ObjectId(moderator_id),
                    "role": "moderator"
                })
                
                # Create new memberships
                if request.assigned_clubs:
                    membership_docs = []
                    for club_id in request.assigned_clubs:
                        membership_doc = {
                            "_id": ObjectId(),
                            "user_id": ObjectId(moderator_id),
                            "club_id": ObjectId(club_id),
                            "role": "moderator",
                            "joined_date": datetime.now(timezone.utc),
                            "is_active": True,
                            "assigned_by_admin_id": admin_id,
                            "request_id": request.request_id,
                            "subscription_status": "active"
                        }
                        membership_docs.append(membership_doc)
                    
                    await club_memberships_collection.insert_many(membership_docs)
                
                changes_made.append(f"Club assignments updated: {len(request.assigned_clubs)} clubs")
            
            # Step 5: Update user document
            if user_updates:
                user_updates["last_updated_timestamp"] = datetime.now(timezone.utc)
                await users_collection.update_one(
                    {"_id": ObjectId(moderator_id)},
                    {"$set": user_updates}
                )
            
            # Step 6: Get updated moderator data
            updated_moderator = await self._get_moderator_details(moderator_id)
            admin_name = await self._get_admin_name(admin_id)
            
            # Step 7: Log successful action
            action_logged = await self._log_action_result(
                ModeratorActionType.EDIT, moderator_id, admin_id, admin_email,
                captain_request["captain_id"], captain_request["captain_name"],
                captain_request["club_id"], request.request_id,
                captain_request["reason"], "success", None, changes_made
            )
            
            print(f"✅ Moderator updated successfully: {moderator_id}")
            
            return ModeratorUpdateResponse(
                success=True,
                message=f"Moderator updated successfully",
                moderator=updated_moderator,
                request_id=request.request_id,
                action_logged=action_logged,
                changes_made=changes_made
            )
            
        except Exception as e:
            error_msg = f"Failed to update moderator: {str(e)}"
            print(f"❌ Error updating moderator: {e}")
            
            # Log failed action
            action_logged = await self._log_action_result(
                ModeratorActionType.EDIT, moderator_id, admin_id, admin_email,
                "unknown", "unknown", "unknown", request.request_id,
                "moderator update", "denied", error_msg
            )
            
            return ModeratorUpdateResponse(
                success=False,
                message=error_msg,
                request_id=request.request_id,
                action_logged=action_logged,
                changes_made=[]
            )
    
    async def delete_moderator(self, moderator_id: str, request: ModeratorDeleteRequest, 
                             admin_email: str, admin_id: str) -> ModeratorDeleteResponse:
        """
        Delete (soft delete) a moderator with Captain approval validation
        
        Args:
            moderator_id: ID of moderator to delete
            request: Moderator deletion request with approved Captain request ID
            admin_email: Email of admin performing the action
            admin_id: ID of admin performing the action
        
        Returns:
            ModeratorDeleteResponse with success status
        """
        try:
            print(f"🗑️ Deleting moderator {moderator_id} with request ID: {request.request_id}")
            
            # Step 1: Validate moderator exists
            moderator = await users_collection.find_one({
                "_id": ObjectId(moderator_id),
                "role": "moderator",
                "is_deleted": False
            })
            
            if not moderator:
                error_msg = f"Moderator with ID {moderator_id} not found"
                return ModeratorDeleteResponse(
                    success=False,
                    message=error_msg,
                    request_id=request.request_id,
                    action_logged=await self._log_action_result(
                        ModeratorActionType.DELETE, moderator_id, admin_id, admin_email,
                        "unknown", "unknown", "unknown", request.request_id,
                        "moderator deletion", "denied", error_msg
                    ),
                    deleted_moderator_id=moderator_id
                )
            
            # Step 2: Validate Captain request
            captain_request = await self._validate_captain_request(
                request.request_id, ModeratorActionType.DELETE, moderator_id
            )
            
            if not captain_request["is_valid"]:
                return ModeratorDeleteResponse(
                    success=False,
                    message=captain_request["error"],
                    request_id=request.request_id,
                    action_logged=await self._log_action_result(
                        ModeratorActionType.DELETE, moderator_id, admin_id, admin_email,
                        captain_request["captain_id"], captain_request["captain_name"],
                        captain_request["club_id"], request.request_id,
                        captain_request["reason"], "denied", captain_request["error"]
                    ),
                    deleted_moderator_id=moderator_id
                )
            
            # Step 3: Soft delete moderator and memberships
            now = datetime.now(timezone.utc)
            
            # Soft delete user
            await users_collection.update_one(
                {"_id": ObjectId(moderator_id)},
                {
                    "$set": {
                        "is_deleted": True,
                        "is_active": False,
                        "deleted_timestamp": now,
                        "deleted_by_admin_id": admin_id,
                        "deletion_request_id": request.request_id
                    }
                }
            )
            
            # Deactivate memberships
            await club_memberships_collection.update_many(
                {"user_id": ObjectId(moderator_id)},
                {
                    "$set": {
                        "is_active": False,
                        "deactivated_timestamp": now,
                        "deactivated_by_admin_id": admin_id
                    }
                }
            )
            
            # Step 4: Log successful action
            changes_made = [
                f"Deleted moderator: {moderator['full_name']}",
                f"Email: {moderator['email']}",
                "All club memberships deactivated"
            ]
            
            if request.delete_reason:
                changes_made.append(f"Deletion reason: {request.delete_reason}")
            
            action_logged = await self._log_action_result(
                ModeratorActionType.DELETE, moderator_id, admin_id, admin_email,
                captain_request["captain_id"], captain_request["captain_name"],
                captain_request["club_id"], request.request_id,
                captain_request["reason"], "success", None, changes_made
            )
            
            print(f"✅ Moderator deleted successfully: {moderator_id}")
            
            return ModeratorDeleteResponse(
                success=True,
                message=f"Moderator {moderator['full_name']} deleted successfully",
                request_id=request.request_id,
                action_logged=action_logged,
                deleted_moderator_id=moderator_id
            )
            
        except Exception as e:
            error_msg = f"Failed to delete moderator: {str(e)}"
            print(f"❌ Error deleting moderator: {e}")
            
            # Log failed action
            action_logged = await self._log_action_result(
                ModeratorActionType.DELETE, moderator_id, admin_id, admin_email,
                "unknown", "unknown", "unknown", request.request_id,
                "moderator deletion", "denied", error_msg
            )
            
            return ModeratorDeleteResponse(
                success=False,
                message=error_msg,
                request_id=request.request_id,
                action_logged=action_logged,
                deleted_moderator_id=moderator_id
            )
    
    # ========================================
    # Private Helper Methods
    # ========================================
    
    async def _validate_captain_request(self, request_id: str, action_type: ModeratorActionType, 
                                      moderator_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Validate that a Captain request exists and is approved
        
        Args:
            request_id: ID of the Captain request
            action_type: Type of action being requested
            moderator_id: ID of moderator (for edit/delete actions)
        
        Returns:
            Dict with validation result and request details
        """
        try:
            # Find the request
            request_query = {
                "request_id": request_id,
                "action_type": action_type.value,
                "request_status": ModeratorRequestStatus.APPROVED.value
            }
            
            # For edit/delete actions, ensure moderator_id matches
            if moderator_id and action_type in [ModeratorActionType.EDIT, ModeratorActionType.DELETE]:
                request_query["moderator_id"] = moderator_id
            
            captain_request = await moderator_requests_collection.find_one(request_query)
            
            if not captain_request:
                return {
                    "is_valid": False,
                    "error": f"No approved {action_type.value} request found with ID {request_id}",
                    "captain_id": "unknown",
                    "captain_name": "unknown",
                    "club_id": "unknown",
                    "reason": "unknown"
                }
            
            # Check if request is recent (within 24 hours)
            request_time = captain_request.get("request_timestamp")
            if request_time:
                time_diff = datetime.now(timezone.utc) - request_time.replace(tzinfo=timezone.utc)
                if time_diff.days > 1:
                    return {
                        "is_valid": False,
                        "error": f"Request {request_id} is expired (older than 24 hours)",
                        "captain_id": captain_request.get("requested_by_captain_id", "unknown"),
                        "captain_name": captain_request.get("captain_name", "unknown"),
                        "club_id": captain_request.get("club_id", "unknown"),
                        "reason": captain_request.get("request_reason", "unknown")
                    }
            
            return {
                "is_valid": True,
                "error": None,
                "captain_id": captain_request.get("requested_by_captain_id", "unknown"),
                "captain_name": captain_request.get("captain_name", "unknown"),
                "club_id": captain_request.get("club_id", "unknown"),
                "reason": captain_request.get("request_reason", "unknown")
            }
            
        except Exception as e:
            print(f"❌ Error validating captain request: {e}")
            return {
                "is_valid": False,
                "error": f"Failed to validate request: {str(e)}",
                "captain_id": "unknown",
                "captain_name": "unknown",
                "club_id": "unknown",
                "reason": "unknown"
            }
    
    async def _check_email_uniqueness(self, email: str, exclude_moderator_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Check if email is unique among moderators
        
        Args:
            email: Email to check
            exclude_moderator_id: Moderator ID to exclude from check (for updates)
        
        Returns:
            Dict with uniqueness result
        """
        try:
            query = {
                "email": email.lower(),
                "role": "moderator",
                "is_deleted": False
            }
            
            if exclude_moderator_id:
                query["_id"] = {"$ne": ObjectId(exclude_moderator_id)}
            
            existing_user = await users_collection.find_one(query)
            
            return {
                "is_unique": existing_user is None,
                "existing_user_id": str(existing_user["_id"]) if existing_user else None
            }
            
        except Exception as e:
            print(f"❌ Error checking email uniqueness: {e}")
            return {"is_unique": False, "existing_user_id": None}
    
    async def _validate_clubs_exist(self, club_ids: List[str]) -> Dict[str, Any]:
        """
        Validate that all club IDs exist and are active
        
        Args:
            club_ids: List of club IDs to validate
        
        Returns:
            Dict with validation result and club details
        """
        try:
            object_ids = [ObjectId(club_id) for club_id in club_ids]
            
            clubs_cursor = clubs_collection.find({
                "_id": {"$in": object_ids},
                "is_deleted": {"$ne": True}
            })
            
            existing_clubs = await clubs_cursor.to_list(length=None)
            existing_ids = {str(club["_id"]): club["name"] for club in existing_clubs}
            
            invalid_clubs = [club_id for club_id in club_ids if club_id not in existing_ids]
            
            return {
                "all_exist": len(invalid_clubs) == 0,
                "invalid_clubs": invalid_clubs,
                "clubs": existing_ids
            }
            
        except Exception as e:
            print(f"❌ Error validating clubs: {e}")
            return {
                "all_exist": False,
                "invalid_clubs": club_ids,
                "clubs": {}
            }
    
    async def _get_moderator_details(self, moderator_id: str) -> ModeratorData:
        """
        Get detailed moderator information
        
        Args:
            moderator_id: ID of moderator
        
        Returns:
            ModeratorData object
        """
        try:
            # Get user data
            user = await users_collection.find_one({"_id": ObjectId(moderator_id)})
            
            # Get club memberships
            # Query for both ObjectId and string formats to handle inconsistent data storage
            memberships_cursor = club_memberships_collection.find({
                "$and": [
                    {
                        "$or": [
                            {"user_id": ObjectId(moderator_id)},
                            {"user_id": moderator_id}
                        ]
                    },
                    {"is_active": True}
                ]
            })
            memberships = await memberships_cursor.to_list(length=None)
            
            # Get club details
            club_ids = [membership["club_id"] for membership in memberships]
            clubs_cursor = clubs_collection.find({"_id": {"$in": club_ids}})
            clubs = await clubs_cursor.to_list(length=None)
            clubs_dict = {str(club["_id"]): club["name"] for club in clubs}
            
            # Get admin name
            admin_name = await self._get_admin_name(user.get("created_by_admin_id"))
            
            assigned_clubs = [
                {"club_id": str(membership["club_id"]), "club_name": clubs_dict.get(str(membership["club_id"]), "Unknown")}
                for membership in memberships
            ]
            
            return ModeratorData(
                moderator_id=moderator_id,
                moderator_name=user["full_name"],
                email=user["email"],
                phone=user.get("phone"),
                assigned_clubs=assigned_clubs,
                roles=user.get("moderator_roles", []),
                is_active=user.get("is_active", False),
                created_by_admin_id=user.get("created_by_admin_id", "unknown"),
                created_by_admin_name=admin_name,
                created_timestamp=user["created_timestamp"].strftime("%d %b %Y %H:%M"),
                last_updated_timestamp=user.get("last_updated_timestamp").strftime("%d %b %Y %H:%M") if user.get("last_updated_timestamp") else None
            )
            
        except Exception as e:
            print(f"❌ Error getting moderator details: {e}")
            raise e
    
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
    
    async def _log_action_result(self, action_type: ModeratorActionType, moderator_id: Optional[str],
                               admin_id: str, admin_email: str, captain_id: str, captain_name: str,
                               club_id: str, request_id: str, request_reason: str, 
                               action_result: str, error_message: Optional[str] = None,
                               changes_made: Optional[List[str]] = None) -> bool:
        """
        Log moderator action result for audit purposes
        
        Args:
            action_type: Type of action performed
            moderator_id: ID of affected moderator
            admin_id: ID of admin who performed action
            admin_email: Email of admin
            captain_id: ID of captain who requested action
            captain_name: Name of captain
            club_id: ID of associated club
            request_id: ID of original request
            request_reason: Reason for the request
            action_result: Result of action ("success" or "denied")
            error_message: Error message if action failed
            changes_made: List of changes made (for successful actions)
        
        Returns:
            True if logging successful, False otherwise
        """
        try:
            log_entry = {
                "_id": ObjectId(),
                "log_id": str(uuid.uuid4()),
                "action_type": action_type.value,
                "moderator_id": moderator_id,
                "admin_id": admin_id,
                "admin_email": admin_email,
                "captain_id": captain_id,
                "captain_name": captain_name,
                "club_id": club_id,
                "request_id": request_id,
                "request_reason": request_reason,
                "action_timestamp": datetime.now(timezone.utc),
                "action_result": action_result,
                "error_message": error_message,
                "changes_made": changes_made or []
            }
            
            await moderator_audit_logs_collection.insert_one(log_entry)
            print(f"📝 Audit log created: {action_type.value} - {action_result}")
            return True
            
        except Exception as e:
            print(f"❌ Error logging action result: {e}")
            return False

# Create service instance
admin_moderator_management_service = AdminModeratorManagementService()