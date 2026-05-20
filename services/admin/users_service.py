import os
import bcrypt
import time
import csv
import io
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from .db import users_collection, audit_logs_collection, search_logs_collection, export_logs_collection
from .models import (
    UserListRequest, UserResponse, PaginationMetadata, UserListResponse,
    AddUserRequest, EditUserRequest, AuditLog, UserStatus, UserRole,
    UserSearchRequest, UserSearchResponse, SearchLog,
    UserExportRequest, UserExportResponse, ExportLog
)

class AdminUsersService:
    def __init__(self):
        self.users_collection = users_collection
        self.audit_logs_collection = audit_logs_collection
        self.search_logs_collection = search_logs_collection
        self.export_logs_collection = export_logs_collection
    
    async def export_users_to_csv(self, request: UserExportRequest, admin_email: str, ip_address: Optional[str] = None) -> UserExportResponse:
        """Export users to CSV with comprehensive filtering and logging"""
        start_time = time.time()
        
        try:
            # Build query filter
            query_filter = {}
            
            # Handle deleted users filter
            if not request.include_deleted:
                query_filter["is_deleted"] = {"$ne": True}
            
            # Name search (case-insensitive partial match)
            if request.name:
                name_regex = {"$regex": request.name, "$options": "i"}
                query_filter["full_name"] = name_regex
            
            # Email search (case-insensitive partial match)
            if request.email:
                email_regex = {"$regex": request.email, "$options": "i"}
                query_filter["email"] = email_regex
            
            # Build query filter for export
            query_filter = {}
            
            # Handle deleted users filter
            if not request.include_deleted:
                query_filter["is_deleted"] = {"$ne": True}
            
            # Name search (case-insensitive partial match)
            if request.name:
                name_regex = {"$regex": request.name, "$options": "i"}
                query_filter["full_name"] = name_regex
            
            # Email search (case-insensitive partial match)
            if request.email:
                email_regex = {"$regex": request.email, "$options": "i"}
                query_filter["email"] = email_regex
            
            # Status filter
            if request.status:
                if request.status.value == "inactive":
                    # For inactive status, include both inactive and deleted users
                    query_filter = {
                        "$or": [
                            {"status": "inactive", "is_deleted": False},
                            {"is_deleted": True}
                        ]
                    }
                    # Re-add name and email filters if they exist
                    if request.name or request.email:
                        additional_filters = {}
                        if request.name:
                            name_regex = {"$regex": request.name, "$options": "i"}
                            additional_filters["full_name"] = name_regex
                        if request.email:
                            email_regex = {"$regex": request.email, "$options": "i"}
                            additional_filters["email"] = email_regex
                        
                        query_filter = {
                            "$and": [
                                query_filter,
                                additional_filters
                            ]
                        }
                else:
                    # For other statuses, just add status filter
                    query_filter["status"] = request.status.value
            
            # Role filter
            if request.role:
                query_filter["role"] = request.role.value
            
            # Date range filter
            if request.date_from or request.date_to:
                date_filter = {}
                if request.date_from:
                    date_filter["$gte"] = request.date_from
                if request.date_to:
                    date_filter["$lte"] = request.date_to
                query_filter["created_at"] = date_filter
            
            # Get total count for export
            total_users = await self.users_collection.count_documents(query_filter)
            
            if total_users == 0:
                return UserExportResponse(
                    success=False,
                    message="No users found matching the export criteria",
                    total_records=0,
                    export_metadata={
                        "export_criteria": self._get_export_criteria_dict(request),
                        "response_time_ms": int((time.time() - start_time) * 1000),
                        "error": "No matching records"
                    }
                )
            
            # Build sort criteria
            sort_field = request.sort_by.value
            
            # Map sort fields to actual database fields
            db_sort_field = self._map_sort_field_to_db_field(sort_field)
            
            sort_direction = 1 if request.sort_order.value == "asc" else -1
            sort_criteria = [(db_sort_field, sort_direction)]
            
            # Add secondary sort by _id for consistent ordering
            if db_sort_field != "_id":
                sort_criteria.append(("_id", sort_direction))
            
            # Execute query with sorting (no pagination for export)
            cursor = self.users_collection.find(query_filter).sort(sort_criteria)
            
            # Define default fields to export
            default_fields = [
                'user_id', 'full_name', 'email', 'phone', 'role', 'status',
                'date_joined', 'last_login', 'is_verified', 'membership_count',
                'total_clubs', 'is_deleted', 'deleted_at', 'membership_status',
                'membership_type', 'subscription_id', 'stripe_customer_id',
                'club_memberships_count'
            ]
            
            # Use requested fields or default fields
            export_fields = request.fields if request.fields else default_fields
            
            # Generate CSV content
            csv_content = await self._generate_csv_content(cursor, export_fields)
            
            # Calculate response time
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Generate filename
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"users_export_{timestamp}_{total_users}_records.csv"
            
            # Save file (in a real implementation, you might save to cloud storage)
            file_size_bytes = len(csv_content.encode('utf-8'))
            
            # Create export metadata
            export_metadata = {
                "export_criteria": self._get_export_criteria_dict(request),
                "response_time_ms": response_time_ms,
                "total_records": total_users,
                "export_fields": export_fields,
                "file_size_bytes": file_size_bytes,
                "filename": filename
            }
            
            # Log export request
            await self._log_export_request(request, admin_email, ip_address, response_time_ms, total_users, filename, file_size_bytes)
            
            # In a real implementation, you would save the file to cloud storage
            # and return a download URL. For now, we'll return the filename
            download_url = f"/api/admin/users/export/download/{filename}"
            
            return UserExportResponse(
                success=True,
                message=f"Export completed in {response_time_ms}ms. {total_users} records exported.",
                download_url=download_url,
                filename=filename,
                csv_content=csv_content,  # Return the actual CSV data
                total_records=total_users,
                export_metadata=export_metadata
            )
            
        except Exception as e:
            print(f"Error in export_users_to_csv: {e}")
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Log failed export
            await self._log_export_request(request, admin_email, ip_address, response_time_ms, 0, "failed", 0, error=str(e))
            
            return UserExportResponse(
                success=False,
                message=f"Export failed: {str(e)}",
                total_records=0,
                export_metadata={
                    "error": str(e),
                    "response_time_ms": response_time_ms
                }
            )
    
    async def _generate_csv_content(self, cursor, export_fields: List[str]) -> str:
        """Generate CSV content from user cursor"""
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(export_fields)
        
        # Write data rows
        async for user_doc in cursor:
            row = []
            for field in export_fields:
                value = await self._get_field_value(user_doc, field)
                row.append(value)
            writer.writerow(row)
        
        return output.getvalue()
    
    async def _get_field_value(self, user_doc: Dict[str, Any], field: str) -> str:
        """Get formatted field value for CSV export"""
        if field == "user_id":
            return str(user_doc.get("_id", ""))
        elif field == "full_name":
            return user_doc.get("full_name", "")
        elif field == "email":
            return user_doc.get("email", "")
        elif field == "phone":
            return user_doc.get("phone", "")
        elif field == "role":
            return user_doc.get("role", "")
        elif field == "status":
            return user_doc.get("status", "")
        elif field == "date_joined":
            date_val = user_doc.get("created_at")
            if isinstance(date_val, datetime):
                return date_val.isoformat()
            elif isinstance(date_val, str):
                return date_val
            else:
                return ""
        elif field == "last_login":
            date_val = user_doc.get("last_login")
            if isinstance(date_val, datetime):
                return date_val.isoformat()
            elif isinstance(date_val, str):
                return date_val
            else:
                return ""
        elif field == "is_verified":
            return str(user_doc.get("is_verified", False)).lower()
        elif field == "membership_count":
            return str(user_doc.get("membership_count", 0))
        elif field == "total_clubs":
            return str(user_doc.get("total_clubs_joined", 0))
        elif field == "is_deleted":
            return str(user_doc.get("is_deleted", False)).lower()
        elif field == "deleted_at":
            date_val = user_doc.get("deleted_at")
            if isinstance(date_val, datetime):
                return date_val.isoformat()
            elif isinstance(date_val, str):
                return date_val
            else:
                return ""
        elif field == "membership_status":
            return user_doc.get("membership_status", "")
        elif field == "membership_type":
            return user_doc.get("membership_type", "")
        elif field == "subscription_id":
            return user_doc.get("subscription_id", "")
        elif field == "stripe_customer_id":
            return user_doc.get("stripe_customer_id", "")
        elif field == "club_memberships_count":
            # Count club memberships for this user
            try:
                from .db import club_memberships_collection
                count = await club_memberships_collection.count_documents({"user_id": ObjectId(user_doc.get("_id"))})
                return str(count)
            except:
                return "0"
        else:
            return str(user_doc.get(field, ""))
    
    def _get_export_criteria_dict(self, request: UserExportRequest) -> Dict[str, Any]:
        """Convert export request to dictionary for logging"""
        return {
            "name": request.name,
            "email": request.email,
            "status": request.status.value if request.status else None,
            "role": request.role.value if request.role else None,
            "date_from": request.date_from.isoformat() if request.date_from else None,
            "date_to": request.date_to.isoformat() if request.date_to else None,
            "sort_by": request.sort_by.value,
            "sort_order": request.sort_order.value,
            "include_deleted": request.include_deleted,
            "fields": request.fields
        }
    
    async def _log_export_request(self, request: UserExportRequest, admin_email: str, ip_address: Optional[str], 
                                 response_time_ms: int, total_records: int, filename: str, file_size_bytes: int, 
                                 error: Optional[str] = None):
        """Log export request for analytics and monitoring"""
        try:
            export_log = {
                "admin_email": admin_email,
                "export_criteria": self._get_export_criteria_dict(request),
                "total_records": total_records,
                "filename": filename,
                "timestamp": datetime.now(timezone.utc),
                "ip_address": ip_address,
                "response_time_ms": response_time_ms,
                "file_size_bytes": file_size_bytes,
                "error": error
            }
            
            await self.export_logs_collection.insert_one(export_log)
            
        except Exception as e:
            print(f"Error logging export request: {e}")
    
    async def search_users(self, request: UserSearchRequest, admin_email: str, ip_address: Optional[str] = None) -> UserSearchResponse:
        """Advanced search users with comprehensive filtering and logging"""
        start_time = time.time()
        
        try:
            # Build query filter
            query_filter = {}
            
            # Exclude deleted users by default
            query_filter["is_deleted"] = {"$ne": True}
            
            # Name search (case-insensitive partial match)
            if request.name:
                name_regex = {"$regex": request.name, "$options": "i"}
                query_filter["full_name"] = name_regex
            
            # Email search (case-insensitive partial match)
            if request.email:
                email_regex = {"$regex": request.email, "$options": "i"}
                query_filter["email"] = email_regex
            
            # Status filter
            if request.status:
                query_filter["status"] = request.status.value
            
            # Date range filter
            if request.date_from or request.date_to:
                date_filter = {}
                if request.date_from:
                    date_filter["$gte"] = request.date_from
                if request.date_to:
                    date_filter["$lte"] = request.date_to
                query_filter["created_at"] = date_filter
            
            # Get total count for pagination
            total_users = await self.users_collection.count_documents(query_filter)
            
            # Calculate pagination
            skip = (request.page - 1) * request.limit
            total_pages = (total_users + request.limit - 1) // request.limit
            has_next = request.page < total_pages
            has_prev = request.page > 1
            
            # Build sort criteria
            sort_field = request.sort_by.value
            sort_direction = 1 if request.sort_order.value == "asc" else -1
            sort_criteria = [(sort_field, sort_direction)]
            
            # Add secondary sort by _id for consistent ordering
            if sort_field != "_id":
                sort_criteria.append(("_id", sort_direction))
            
            # Execute query with pagination and sorting
            cursor = self.users_collection.find(query_filter).sort(sort_criteria).skip(skip).limit(request.limit)
            
            # Convert to response models
            users = []
            async for user_doc in cursor:
                user_response = await self._convert_to_user_response(user_doc)
                users.append(user_response)
            
            # Calculate response time
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Create pagination metadata
            pagination = PaginationMetadata(
                total_users=total_users,
                current_page=request.page,
                total_pages=total_pages,
                has_next=has_next,
                has_prev=has_prev,
                limit=request.limit
            )
            
            # Create search metadata
            search_metadata = {
                "search_criteria": {
                    "name": request.name,
                    "email": request.email,
                    "status": request.status.value if request.status else None,
                    "date_from": request.date_from.isoformat() if request.date_from else None,
                    "date_to": request.date_to.isoformat() if request.date_to else None,
                    "sort_by": request.sort_by.value,
                    "sort_order": request.sort_order.value
                },
                "response_time_ms": response_time_ms,
                "results_count": len(users),
                "total_matches": total_users
            }
            
            # Log search request
            await self._log_search_request(request, admin_email, ip_address, response_time_ms, len(users), total_users)
            
            return UserSearchResponse(
                success=True,
                message=f"Search completed in {response_time_ms}ms. Found {total_users} total matches.",
                users=users,
                pagination=pagination,
                search_metadata=search_metadata
            )
            
        except Exception as e:
            print(f"Error in search_users: {e}")
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Log failed search
            await self._log_search_request(request, admin_email, ip_address, response_time_ms, 0, 0, error=str(e))
            
            return UserSearchResponse(
                success=False,
                message=f"Search failed: {str(e)}",
                users=[],
                pagination=PaginationMetadata(
                    total_users=0,
                    current_page=request.page,
                    total_pages=0,
                    has_next=False,
                    has_prev=False,
                    limit=request.limit
                ),
                search_metadata={
                    "error": str(e),
                    "response_time_ms": response_time_ms
                }
            )
    
    async def _log_search_request(self, request: UserSearchRequest, admin_email: str, ip_address: Optional[str], 
                                 response_time_ms: int, results_count: int, total_matches: int, error: Optional[str] = None):
        """Log search request for analytics and monitoring"""
        try:
            search_log = {
                "admin_email": admin_email,
                "search_criteria": {
                    "name": request.name,
                    "email": request.email,
                    "status": request.status.value if request.status else None,
                    "date_from": request.date_from.isoformat() if request.date_from else None,
                    "date_to": request.date_to.isoformat() if request.date_to else None,
                    "sort_by": request.sort_by.value,
                    "sort_order": request.sort_order.value,
                    "page": request.page,
                    "limit": request.limit
                },
                "results_count": results_count,
                "total_matches": total_matches,
                "timestamp": datetime.now(timezone.utc),
                "ip_address": ip_address,
                "response_time_ms": response_time_ms,
                "error": error
            }
            
            await self.search_logs_collection.insert_one(search_log)
            
        except Exception as e:
            print(f"Error logging search request: {e}")
    
    async def get_users(self, request: UserListRequest) -> UserListResponse:
        """Get paginated list of users with search, filtering, and sorting"""
        
        # Build query filter - start with excluding deleted users by default
        # But we'll override this if specifically filtering by deleted status
        query_filter = {"is_deleted": {"$ne": True}}
        
        # Search filter
        search_filter = None
        if request.search:
            search_regex = {"$regex": request.search, "$options": "i"}
            search_filter = {
                "$or": [
                    {"full_name": search_regex},
                    {"email": search_regex},
                    {"phone": search_regex}
                ]
            }
        
        # Status filter
        if request.status:
            if request.status.value == "inactive":
                # For inactive status, include users who are not active
                # This includes inactive, banned, and deleted users
                status_filter = {
                    "$or": [
                        {"status": "inactive"},
                        {"status": "banned"},
                        {"is_deleted": True}
                    ]
                }
                # Combine with existing filters
                query_filter = {"$and": [query_filter, status_filter]}
            elif request.status.value == "deleted":
                # For deleted status, show users with status="deleted"
                # Override the default filter that excludes deleted users
                query_filter = {"status": "deleted"}
            else:
                # For other statuses (active, banned), just add status filter
                query_filter["status"] = request.status.value
        
        # Role filter
        if request.role:
            # Handle case-insensitive role filtering for Moderator/moderator
            if request.role.value == "Moderator":
                role_filter = {"role": {"$in": ["Moderator", "moderator"]}}
            else:
                role_filter = {"role": request.role.value}
            
            # Combine role filter with existing query filter
            if "$and" in query_filter:
                query_filter["$and"].append(role_filter)
            else:
                query_filter = {"$and": [query_filter, role_filter]}
        
        # Combine search filter with main query filter
        if search_filter:
            if "$and" in query_filter:
                query_filter["$and"].append(search_filter)
            else:
                query_filter = {"$and": [query_filter, search_filter]}
        
        # Date range filter
        if request.date_from or request.date_to:
            date_filter = {}
            if request.date_from:
                date_filter["$gte"] = request.date_from
            if request.date_to:
                date_filter["$lte"] = request.date_to
            query_filter["created_at"] = date_filter
        
        # Debug logging
        print(f"Search query: {request.search}")
        print(f"Status filter: {request.status.value if request.status else 'None'}")
        print(f"Role filter: {request.role.value if request.role else 'None'}")
        print(f"Final query filter: {query_filter}")
        
        # Debug: Check what moderators exist in the database
        if request.role and (request.role.value == "Moderator" or request.role.value == "moderator"):
            moderator_sample = await self.users_collection.find({"role": {"$in": ["Moderator", "moderator"]}}).limit(5).to_list(None)
            print(f"Sample moderators in DB: {[(m.get('email', 'No email'), m.get('status', 'No status'), m.get('is_deleted', 'No deleted field')) for m in moderator_sample]}")
        
        # Get total count for pagination
        total_users = await self.users_collection.count_documents(query_filter)
        print(f"Total users found: {total_users}")
        
        # Let's also check what's in the database
        sample_user = await self.users_collection.find_one({})
        if sample_user:
            print(f"Sample user in DB: {sample_user.get('email', 'No email')} - Status: {sample_user.get('status', 'No status')} - Deleted: {sample_user.get('is_deleted', 'No deleted field')}")
        else:
            print("No users found in database at all")
        
        # Calculate pagination
        skip = (request.page - 1) * request.limit
        total_pages = (total_users + request.limit - 1) // request.limit
        has_next = request.page < total_pages
        has_prev = request.page > 1
        
        # Build sort criteria
        sort_field = request.sort_by.value  # Get the enum value
        
        # Map sort fields to actual database fields
        db_sort_field = self._map_sort_field_to_db_field(sort_field)
        
        sort_direction = 1 if request.sort_order.value == "asc" else -1
        sort_criteria = [(db_sort_field, sort_direction)]
        
        # Add secondary sort by _id for consistent ordering
        if db_sort_field != "_id":
            sort_criteria.append(("_id", sort_direction))
        
        # Execute query with pagination and sorting
        cursor = self.users_collection.find(query_filter).sort(sort_criteria).skip(skip).limit(request.limit)
        
        # Convert to response models (simplified for listing)
        users = []
        async for user_doc in cursor:
            user_response = await self._convert_to_user_response_simple(user_doc)
            users.append(user_response)
        
        # Create pagination metadata
        pagination = PaginationMetadata(
            total_users=total_users,
            current_page=request.page,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
            limit=request.limit
        )
        
        # Create simplified response with only required fields
        return {
            "success": True,
            "message": f"Retrieved {len(users)} users",
            "users": users,
            "pagination": {
                "total_users": pagination.total_users,
                "current_page": pagination.current_page,
                "total_pages": pagination.total_pages,
                "has_next": pagination.has_next,
                "has_prev": pagination.has_prev,
                "limit": pagination.limit
            }
        }
    
    async def add_user(self, request: AddUserRequest, admin_email: str, ip_address: Optional[str] = None) -> Dict[str, Any]:
        """Add a new user with validation and audit logging"""
        try:
            # Check if email already exists
            existing_user = await self.users_collection.find_one({"email": request.email})
            if existing_user:
                return {
                    "success": False,
                    "message": "User with this email already exists",
                    "error": "EMAIL_EXISTS"
                }
            
            # Hash password
            password_hash = bcrypt.hashpw(request.password.encode(), bcrypt.gensalt()).decode()
            
            # Create user document
            user_doc = {
                "full_name": request.name,
                "email": request.email,
                "phone": request.phone or "",
                "role": request.role.value,
                "status": request.status.value,
                "password_hash": password_hash,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "is_verified": False,
                "is_deleted": False,
                "membership_count": 0,
                "total_clubs": 0
            }
            
            # Insert user
            result = await self.users_collection.insert_one(user_doc)
            user_id = str(result.inserted_id)
            
            # Create audit log
            audit_log = {
                "action": "create",
                "admin_email": admin_email,
                "user_id": user_id,
                "changes": {
                    "name": request.name,
                    "email": request.email,
                    "role": request.role.value,
                    "status": request.status.value
                },
                "timestamp": datetime.now(timezone.utc),
                "ip_address": ip_address
            }
            await self.audit_logs_collection.insert_one(audit_log)
            
            # Get the created user
            created_user = await self._convert_to_user_response(user_doc)
            
            return {
                "success": True,
                "message": "User created successfully",
                "user_id": user_id,
                "user": created_user
            }
            
        except Exception as e:
            print(f"Error adding user: {e}")
            return {
                "success": False,
                "message": f"Error creating user: {str(e)}",
                "error": "INTERNAL_ERROR"
            }
    
    async def edit_user(self, user_id: str, request: EditUserRequest, admin_email: str, ip_address: Optional[str] = None) -> Dict[str, Any]:
        """Edit an existing user with validation and audit logging"""
        try:
            # Check if user exists
            existing_user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not existing_user:
                return {
                    "success": False,
                    "message": "User not found",
                    "error": "USER_NOT_FOUND"
                }
            
            # Check if user is deleted
            if existing_user.get("is_deleted", False):
                return {
                    "success": False,
                    "message": "Cannot edit deleted user",
                    "error": "USER_DELETED"
                }
            
            # Check email uniqueness if email is being changed
            if request.email and request.email != existing_user.get("email"):
                email_exists = await self.users_collection.find_one({"email": request.email})
                if email_exists:
                    return {
                        "success": False,
                        "message": "Email already exists",
                        "error": "EMAIL_EXISTS"
                    }
            
            # Build update document
            update_doc = {"updated_at": datetime.now(timezone.utc)}
            changes = {}
            
            if request.name is not None:
                update_doc["full_name"] = request.name
                changes["name"] = request.name
            
            if request.email is not None:
                update_doc["email"] = request.email
                changes["email"] = request.email
            
            if request.phone is not None:
                update_doc["phone"] = request.phone
                changes["phone"] = request.phone
            
            if request.status is not None:
                update_doc["status"] = request.status.value
                changes["status"] = request.status.value
            
            if request.role is not None:
                update_doc["role"] = request.role.value
                changes["role"] = request.role.value
            
            # Update user
            result = await self.users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_doc}
            )
            
            if result.modified_count == 0:
                return {
                    "success": False,
                    "message": "No changes made to user",
                    "error": "NO_CHANGES"
                }
            
            # Create audit log
            audit_log = {
                "action": "update",
                "admin_email": admin_email,
                "user_id": user_id,
                "changes": changes,
                "timestamp": datetime.now(timezone.utc),
                "ip_address": ip_address
            }
            await self.audit_logs_collection.insert_one(audit_log)
            
            # Get updated user
            updated_user_doc = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            updated_user = await self._convert_to_user_response(updated_user_doc)
            
            return {
                "success": True,
                "message": "User updated successfully",
                "user_id": user_id,
                "user": updated_user,
                "changes": changes
            }
            
        except Exception as e:
            print(f"Error editing user: {e}")
            return {
                "success": False,
                "message": f"Error updating user: {str(e)}",
                "error": "INTERNAL_ERROR"
            }
    
    async def delete_user(self, user_id: str, admin_email: str, ip_address: Optional[str] = None) -> Dict[str, Any]:
        """Soft delete a user with audit logging and membership deactivation"""
        try:
            # Check if user exists
            existing_user = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not existing_user:
                return {
                    "success": False,
                    "message": "User not found",
                    "error": "USER_NOT_FOUND"
                }
            
            # Check if user is already deleted
            if existing_user.get("is_deleted", False):
                return {
                    "success": False,
                    "message": "User is already deleted",
                    "error": "ALREADY_DELETED"
                }
            
            # Get user email for notification
            user_email = existing_user.get("email", "")
            user_name = existing_user.get("full_name", "")
            
            # Soft delete user with comprehensive updates
            current_time = datetime.now(timezone.utc)
            result = await self.users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "is_deleted": True,
                        "deleted_at": current_time,
                        "status": "inactive",
                        "membership_status": "inactive",
                        "updated_at": current_time
                    }
                }
            )
            
            if result.modified_count == 0:
                return {
                    "success": False,
                    "message": "Failed to delete user",
                    "error": "DELETE_FAILED"
                }
            
            # Update club memberships to inactive status
            await self._deactivate_user_club_memberships(user_id, current_time)
            
            # Send email notification about membership ending
            if user_email:
                await self._send_membership_termination_email(user_email, user_name, admin_email)
            
            # Create audit log
            audit_log = {
                "action": "delete",
                "admin_email": admin_email,
                "user_id": user_id,
                "changes": {
                    "is_deleted": True,
                    "deleted_at": current_time.isoformat(),
                    "status": "inactive",
                    "membership_status": "inactive"
                },
                "timestamp": current_time,
                "ip_address": ip_address
            }
            await self.audit_logs_collection.insert_one(audit_log)
            
            return {
                "success": True,
                "message": "User deleted successfully and membership deactivated",
                "user_id": user_id,
                "deleted_at": current_time.isoformat(),
                "email_sent": bool(user_email)
            }
            
        except Exception as e:
            print(f"Error deleting user: {e}")
            return {
                "success": False,
                "message": f"Error deleting user: {str(e)}",
                "error": "INTERNAL_ERROR"
            }
    
    async def _convert_to_user_response(self, user_doc: Dict[str, Any]) -> UserResponse:
        """Convert database user document to UserResponse model (full details)"""
        
        # Get user ID
        user_id = str(user_doc.get("_id", ""))
        
        # Get basic user info
        full_name = user_doc.get("full_name", "")
        email = user_doc.get("email", "")
        phone = user_doc.get("phone", "")
        role = user_doc.get("role", "member")
        
        # Get status (default to active if not specified)
        status = user_doc.get("status", "active")
        
        # Get dates
        created_at = user_doc.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except:
                created_at = datetime.now(timezone.utc)
        elif not created_at:
            created_at = datetime.now(timezone.utc)
        
        last_login = user_doc.get("last_login")
        if isinstance(last_login, str):
            try:
                last_login = datetime.fromisoformat(last_login.replace('Z', '+00:00'))
            except:
                last_login = None
        
        # Get profile picture
        profile_picture = user_doc.get("profile_picture")
        
        # Get verification status
        is_verified = user_doc.get("is_verified", False)
        
        # Get membership and club counts
        membership_count = user_doc.get("membership_count", 0)
        total_clubs = user_doc.get("total_clubs_joined", 0)
        
        # Get deletion info
        is_deleted = user_doc.get("is_deleted", False)
        deleted_at = user_doc.get("deleted_at")
        if isinstance(deleted_at, str):
            try:
                deleted_at = datetime.fromisoformat(deleted_at.replace('Z', '+00:00'))
            except:
                deleted_at = None
        
        # Get admin deletion flags
        is_deleted_per_admin = user_doc.get("is_deleted_per_admin", False)
        is_deleted_temp_admin = user_doc.get("is_deleted_temp_admin", False)
        
        # Get membership and plan details
        membership_status = user_doc.get("membership_status", "inactive")
        membership_type = user_doc.get("membership_type", None)
        subscription_id = user_doc.get("subscription_id", None)
        stripe_customer_id = user_doc.get("stripe_customer_id", None)
        plan_start_date = user_doc.get("plan_start_date", None)
        plan_end_date = user_doc.get("plan_end_date", None)
        
        # Convert plan dates if they exist
        if isinstance(plan_start_date, str):
            try:
                plan_start_date = datetime.fromisoformat(plan_start_date.replace('Z', '+00:00'))
            except:
                plan_start_date = None
        
        if isinstance(plan_end_date, str):
            try:
                plan_end_date = datetime.fromisoformat(plan_end_date.replace('Z', '+00:00'))
            except:
                plan_end_date = None
        
        # Determine plan details based on membership status and type
        plan_details = []
        if membership_status == "active" and membership_type in ["trial", "paid"]:
            if membership_type == "trial":
                plan_details = [{
                    "plan_name": "Trial Membership",
                    "price": "$19.95",
                    "plan_start_date": plan_start_date,
                    "plan_end_date": plan_end_date
                }]
            elif membership_type == "paid":
                plan_details = [{
                    "plan_name": "Paid Membership",
                    "price": "$99",
                    "plan_start_date": plan_start_date,
                    "plan_end_date": plan_end_date
                }]
        
        return UserResponse(
            user_id=user_id,
            full_name=full_name,
            email=email,
            phone=phone,
            role=role,
            status=status,
            date_joined=created_at,
            last_login=last_login,
            profile_picture=profile_picture,
            is_verified=is_verified,
            membership_count=membership_count,
            total_clubs=total_clubs,
            is_deleted=is_deleted,
            deleted_at=deleted_at,
            is_deleted_per_admin=is_deleted_per_admin,
            is_deleted_temp_admin=is_deleted_temp_admin,
            membership_status=membership_status,
            membership_type=membership_type,
            subscription_id=subscription_id,
            stripe_customer_id=stripe_customer_id,
            plan_details=plan_details
        )
    
    async def _convert_to_user_response_simple(self, user_doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert database user document to simplified dictionary for listing (only required fields)"""
        
        # Get user ID
        user_id = str(user_doc.get("_id", ""))
        
        # Get basic user info
        full_name = user_doc.get("full_name", "")
        email = user_doc.get("email", "")
        phone = user_doc.get("phone", "")
        role = user_doc.get("role", "member")
        
        # Get status (default to active if not specified)
        status = user_doc.get("status", "active")
        
        # Get date joined
        created_at = user_doc.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except:
                created_at = datetime.now(timezone.utc)
        elif not created_at:
            created_at = datetime.now(timezone.utc)
        
        # Get deletion info
        is_deleted = user_doc.get("is_deleted", False)
        deleted_at = user_doc.get("deleted_at")
        if isinstance(deleted_at, str):
            try:
                deleted_at = datetime.fromisoformat(deleted_at.replace('Z', '+00:00'))
            except:
                deleted_at = None
        
        # Get admin deletion flags
        is_deleted_per_admin = user_doc.get("is_deleted_per_admin", False)
        is_deleted_temp_admin = user_doc.get("is_deleted_temp_admin", False)
        
        # Return simplified response with only required fields
        return {
            "user_id": user_id,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "role": role,
            "status": status,
            "date_joined": created_at,
            "is_deleted": is_deleted,
            "deleted_at": deleted_at.isoformat() if deleted_at else None,
            "is_deleted_per_admin": is_deleted_per_admin,
            "is_deleted_temp_admin": is_deleted_temp_admin
        }
    
    async def get_user_by_id(self, user_id: str) -> Optional[UserResponse]:
        """Get a specific user by ID with club membership details"""
        try:
            user_doc = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if user_doc:
                user_response = await self._convert_to_user_response(user_doc)
                
                # Get club membership details
                club_memberships = await self._get_user_club_memberships(user_id)
                
                # Add club memberships to the user response
                if hasattr(user_response, 'model_dump'):
                    # For Pydantic v2
                    user_dict = user_response.model_dump()
                else:
                    # For Pydantic v1
                    user_dict = user_response.dict()
                
                user_dict['club_memberships'] = club_memberships
                
                # Create a new UserResponse with club memberships
                return UserResponse(**user_dict)
                
        except Exception as e:
            print(f"Error getting user by ID: {e}")
        return None
    
    def _map_sort_field_to_db_field(self, sort_field: str) -> str:
        """Map sort field enum values to actual database field names"""
        field_mapping = {
            "name": "full_name",  # SortField.NAME maps to database field "full_name"
            "date_joined": "created_at",  # SortField.DATE_JOINED maps to database field "created_at"
            "email": "email",  # SortField.EMAIL maps to database field "email"
            "status": "status"  # SortField.STATUS maps to database field "status"
        }
        return field_mapping.get(sort_field, "created_at")  # Default to created_at if unknown
    
    async def _get_user_club_memberships(self, user_id: str) -> List[Dict[str, Any]]:
        """Get club membership details for a user"""
        try:
            # Import club memberships collection
            from .db import club_memberships_collection
            
            # Find all club memberships for this user
            # Query for both ObjectId and string formats to handle inconsistent data storage
            cursor = club_memberships_collection.find({
                "$or": [
                    {"user_id": ObjectId(user_id)},
                    {"user_id": user_id}
                ]
            })
            
            memberships = []
            async for membership in cursor:
                # Get club details with pricing information
                club_details = await self._get_club_details_with_pricing(str(membership.get("club_id")))
                
                # Get pricing plan details
                pricing_details = await self._get_pricing_plan_details(membership, club_details)
                
                membership_info = {
                    "membership_id": str(membership.get("_id")),
                    "club_id": str(membership.get("club_id")),
                    "club_name": club_details.get("name", "Unknown Club"),
                    "club_name_based_id": club_details.get("name_based_id", ""),
                    "club_description": club_details.get("description", ""),
                    "club_category": club_details.get("category", ""),
                    "club_status": club_details.get("status", "active"),
                    "role": membership.get("role", "member"),
                    "status": membership.get("status", "active"),
                    "joined_date": membership.get("joined_date"),
                    "start_date": membership.get("start_date"),
                    "end_date": membership.get("end_date"),
                    "subscription_status": membership.get("subscription_status", "active"),
                    "is_active": membership.get("is_active", True),
                    "pricing_details": pricing_details
                }
                
                # Convert datetime objects to ISO strings
                membership_info = self._convert_membership_datetimes(membership_info)
                
                memberships.append(membership_info)
            
            return memberships
            
        except Exception as e:
            print(f"Error getting club memberships: {e}")
            return []
    
    async def _get_club_details_with_pricing(self, club_id: str) -> Dict[str, Any]:
        """Get club details with pricing information"""
        try:
            # Import clubs collection
            from .db import clubs_collection
            
            club = await clubs_collection.find_one({"_id": ObjectId(club_id)})
            if club:
                return {
                    "name": club.get("name", ""),
                    "name_based_id": club.get("name_based_id", ""),
                    "description": club.get("description", ""),
                    "category": club.get("category", ""),
                    "status": club.get("status", "active"),
                    "pricing_plans": club.get("pricing_plans", []),
                    "captain_id": club.get("captain_id"),
                    "member_count": club.get("member_count", 0),
                    "win_pct": club.get("win_pct", 0.0),
                    "created_at": club.get("created_at")
                }
            return {}
            
        except Exception as e:
            print(f"Error getting club details with pricing: {e}")
            return {}
    
    async def _get_pricing_plan_details(self, membership: Dict[str, Any], club_details: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed pricing plan information for a membership"""
        try:
            # Get the pricing plan from club details
            club_pricing_plans = club_details.get("pricing_plans", [])
            
            # Find the specific pricing plan used by this membership
            membership_plan_id = membership.get("pricing_plan_id")
            pricing_plan = None
            
            if membership_plan_id:
                # Find the specific pricing plan
                for plan in club_pricing_plans:
                    if str(plan.get("_id")) == str(membership_plan_id):
                        pricing_plan = plan
                        break
            
            if not pricing_plan and club_pricing_plans:
                # If no specific plan found, use the first available plan
                pricing_plan = club_pricing_plans[0]
            
            if pricing_plan:
                return {
                    "plan_name": pricing_plan.get("plan", "Standard Plan"),
                    "frequency": pricing_plan.get("frequency", "monthly"),
                    "price": pricing_plan.get("price", 0.0),
                    "currency": pricing_plan.get("currency", "USD"),
                    "stripe_product_id": pricing_plan.get("stripe_product_id"),
                    "stripe_price_id": pricing_plan.get("stripe_price_id"),
                    "is_active": pricing_plan.get("is_active", True),
                    "created_at": pricing_plan.get("created_at"),
                    "updated_at": pricing_plan.get("updated_at")
                }
            else:
                # Fallback pricing information
                return {
                    "plan_name": "Standard Membership",
                    "frequency": "monthly",
                    "price": 0.0,
                    "currency": "USD",
                    "is_active": True
                }
                
        except Exception as e:
            print(f"Error getting pricing plan details: {e}")
            return {
                "plan_name": "Standard Membership",
                "frequency": "monthly",
                "price": 0.0,
                "currency": "USD",
                "is_active": True
            }
    
    def _convert_membership_datetimes(self, membership_info: Dict[str, Any]) -> Dict[str, Any]:
        """Convert datetime objects in membership info to ISO strings"""
        for key, value in membership_info.items():
            if hasattr(value, 'isoformat'):
                membership_info[key] = value.isoformat()
            elif isinstance(value, dict):
                membership_info[key] = self._convert_membership_datetimes(value)
        return membership_info
    
    async def _deactivate_user_club_memberships(self, user_id: str, deactivation_time: datetime):
        """Deactivate all club memberships for a deleted user"""
        try:
            from .db import club_memberships_collection
            
            # Update all club memberships for this user to inactive
            result = await club_memberships_collection.update_many(
                {"user_id": ObjectId(user_id)},
                {
                    "$set": {
                        "status": "inactive",
                        "subscription_status": "inactive",
                        "is_active": False,
                        "deactivated_at": deactivation_time,
                        "updated_at": deactivation_time
                    }
                }
            )
            
            print(f"Deactivated {result.modified_count} club memberships for user {user_id}")
            
        except Exception as e:
            print(f"Error deactivating club memberships for user {user_id}: {e}")
    
    async def _send_membership_termination_email(self, user_email: str, user_name: str, admin_email: str):
        """Send email notification about membership termination"""
        try:
            subject = "Membership Termination Notice"
            
            # Create professional email content
            email_content = f"""
            Dear {user_name},
            
            We regret to inform you that your membership has been terminated by our administration team.
            
            This action was taken on {datetime.now(timezone.utc).strftime('%B %d, %Y at %I:%M %p UTC')}.
            
            As a result of this termination:
            - Your account status has been set to inactive
            - All club memberships have been deactivated
            - Access to premium features has been revoked
            
            If you believe this action was taken in error, please contact our support team.
            
            Thank you for your understanding.
            
            Best regards,
            The Administration Team
            
            ---
            This is an automated notification. Please do not reply to this email.
            """
            
            # Send email using the existing email utility
            from admin.utils.email import send_email
            await send_email(
                to_email=user_email,
                subject=subject,
                body=email_content
            )
            
            print(f"Membership termination email sent to {user_email}")
            
        except Exception as e:
            print(f"Error sending membership termination email to {user_email}: {e}")
    
    async def update_user_status(self, user_id: str, status: str) -> bool:
        """Update user status (Active/Suspended)"""
        try:
            result = await self.users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"status": status}}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error updating user status: {e}")
            return False
    
    async def get_user_statistics(self) -> Dict[str, Any]:
        """Get user statistics for admin dashboard"""
        try:
            # Total users (excluding deleted)
            total_users = await self.users_collection.count_documents({"is_deleted": {"$ne": True}})
            
            # Active users
            active_users = await self.users_collection.count_documents({"status": "active", "is_deleted": {"$ne": True}})
            
            # Inactive users
            inactive_users = await self.users_collection.count_documents({"status": "inactive", "is_deleted": {"$ne": True}})
            
            # Banned users
            banned_users = await self.users_collection.count_documents({"status": "banned", "is_deleted": {"$ne": True}})
            
            # Deleted users
            deleted_users = await self.users_collection.count_documents({"is_deleted": True})
            
            # Users joined today
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            users_today = await self.users_collection.count_documents({
                "created_at": {"$gte": today},
                "is_deleted": {"$ne": True}
            })
            
            # Users joined this month
            month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            users_this_month = await self.users_collection.count_documents({
                "created_at": {"$gte": month_start},
                "is_deleted": {"$ne": True}
            })
            
            return {
                "total_users": total_users,
                "active_users": active_users,
                "inactive_users": inactive_users,
                "banned_users": banned_users,
                "deleted_users": deleted_users,
                "users_today": users_today,
                "users_this_month": users_this_month
            }
        except Exception as e:
            print(f"Error getting user statistics: {e}")
            return {}
    
    async def get_audit_logs(self, user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get audit logs for a user or all audit logs"""
        try:
            query = {}
            if user_id:
                query["user_id"] = user_id
            
            cursor = self.audit_logs_collection.find(query).sort("timestamp", -1).limit(limit)
            logs = []
            async for log in cursor:
                logs.append({
                    "id": str(log["_id"]),
                    "action": log["action"],
                    "admin_email": log["admin_email"],
                    "user_id": log["user_id"],
                    "changes": log.get("changes"),
                    "timestamp": log["timestamp"],
                    "ip_address": log.get("ip_address")
                })
            return logs
        except Exception as e:
            print(f"Error getting audit logs: {e}")
            return []
    
    async def get_search_logs(self, admin_email: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get search logs for analytics"""
        try:
            query = {}
            if admin_email:
                query["admin_email"] = admin_email
            
            cursor = self.search_logs_collection.find(query).sort("timestamp", -1).limit(limit)
            logs = []
            async for log in cursor:
                logs.append({
                    "id": str(log["_id"]),
                    "admin_email": log["admin_email"],
                    "search_criteria": log["search_criteria"],
                    "results_count": log["results_count"],
                    "total_matches": log.get("total_matches", 0),
                    "timestamp": log["timestamp"],
                    "ip_address": log.get("ip_address"),
                    "response_time_ms": log["response_time_ms"],
                    "error": log.get("error")
                })
            return logs
        except Exception as e:
            print(f"Error getting search logs: {e}")
            return []
    
    async def get_export_logs(self, admin_email: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get export logs for analytics"""
        try:
            query = {}
            if admin_email:
                query["admin_email"] = admin_email
            
            cursor = self.export_logs_collection.find(query).sort("timestamp", -1).limit(limit)
            logs = []
            async for log in cursor:
                logs.append({
                    "id": str(log["_id"]),
                    "admin_email": log["admin_email"],
                    "export_criteria": log["export_criteria"],
                    "total_records": log["total_records"],
                    "filename": log["filename"],
                    "timestamp": log["timestamp"],
                    "ip_address": log.get("ip_address"),
                    "response_time_ms": log["response_time_ms"],
                    "file_size_bytes": log.get("file_size_bytes", 0),
                    "error": log.get("error")
                })
            return logs
        except Exception as e:
            print(f"Error getting export logs: {e}")
            return []

    async def get_user_club_counts(self, user_id: str) -> Dict[str, Any]:
        """Get member and moderator counts for a user from clubs table"""
        try:
            # Import clubs collection
            from .db import clubs_collection
            
            # Count clubs where user is a member (in members array)
            member_count = await clubs_collection.count_documents({
                "members.user_id": user_id,
                "is_permanently_deleted": {"$ne": True}
            })
            
            # Count clubs where user is a paid member (in paid_members array)
            paid_member_count = await clubs_collection.count_documents({
                "paid_members.user_id": user_id,
                "is_permanently_deleted": {"$ne": True}
            })
            
            # Count clubs where user is a moderator (in detailed_moderators array)
            moderator_count = await clubs_collection.count_documents({
                "detailed_moderators.user_id": user_id,
                "is_permanently_deleted": {"$ne": True}
            })
            
            # Count clubs where user is a paid moderator (in paid_moderators array)
            paid_moderator_count = await clubs_collection.count_documents({
                "paid_moderators.user_id": user_id,
                "is_permanently_deleted": {"$ne": True}
            })
            
            # Count clubs created by the user (if they're a captain)
            created_clubs_count = await clubs_collection.count_documents({
                "captain_id": user_id,
                "is_permanently_deleted": {"$ne": True}
            })
            
            return {
                "member_count": member_count,
                "paid_member_count": paid_member_count,
                "total_member_count": member_count + paid_member_count,
                "moderator_count": moderator_count,
                "paid_moderator_count": paid_moderator_count,
                "total_moderator_count": moderator_count + paid_moderator_count,
                "created_clubs_count": created_clubs_count,
                "total_clubs_involved": member_count + paid_member_count + moderator_count + paid_moderator_count + created_clubs_count
            }
            
        except Exception as e:
            print(f"Error getting user club counts: {e}")
            return {
                "member_count": 0,
                "paid_member_count": 0,
                "total_member_count": 0,
                "moderator_count": 0,
                "paid_moderator_count": 0,
                "total_moderator_count": 0,
                "created_clubs_count": 0,
                "total_clubs_involved": 0
            }

# Global service instance
admin_users_service = AdminUsersService() 