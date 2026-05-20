#!/usr/bin/env python3
"""
Subscription Plans Management Service

This service handles comprehensive subscription plan management including:
- Paginated, searchable, and sortable plan listing
- Active subscriber count calculation
- CSV export functionality
- Analytics and reporting
- Performance-optimized database queries

Key Features:
- Advanced filtering and search capabilities
- Real-time active subscriber counts
- CSV export with custom field selection
- Performance optimization with aggregation pipelines
- Comprehensive error handling and validation
"""

import asyncio
import csv
import io
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from bson import ObjectId

from .models import (
    SubscriptionPlanListRequest, SubscriptionPlanListResponse,
    SubscriptionPlan, SubscriptionPlanListPagination,
    SubscriptionPlanCSVExportRequest, SubscriptionPlanDetails,
    SubscriptionPlanAnalytics, SubscriptionPlanType, SubscriptionStatus,
    SubscriptionPlanSortField, SortOrder, PlanStatus,
    SubscriptionPlanStatusUpdateRequest, SubscriptionPlanStatusUpdateResponse,
    SubscriptionPlanDeleteResponse,SubscriptionPlanCSVExportResponse
)
from .db import (
    subscription_plans_collection, subscriptions_collection,
    subscription_analytics_collection, subscription_admin_logs_collection
)

class AdminSubscriptionPlansService:
    """
    Service for managing subscription plans with comprehensive functionality
    """
    
    def __init__(self):
        self.service_name = "AdminSubscriptionPlansService"
    
    async def get_subscription_plans_list(self, request: SubscriptionPlanListRequest, 
                                        admin_email: str) -> SubscriptionPlanListResponse:
        """
        Get paginated, searchable, and sortable list of subscription plans with active subscriber counts
        
        Args:
            request: List request with filters, search, sorting, and pagination
            admin_email: Email of admin requesting the list
        
        Returns:
            SubscriptionPlanListResponse with plans and metadata
        """
        try:
            print(f"📋 Admin {admin_email} requesting subscription plans list")
            
            # Step 1: Build aggregation pipeline
            pipeline = await self._build_subscription_plans_aggregation_pipeline(request)
            
            # Step 2: Get total count
            count_pipeline = pipeline + [{"$count": "total"}]
            count_result = await subscription_plans_collection.aggregate(count_pipeline).to_list(length=1)
            total_records = count_result[0]["total"] if count_result else 0
            
            # Step 3: Apply pagination
            skip = (request.page - 1) * request.limit
            paginated_pipeline = pipeline + [
                {"$skip": skip},
                {"$limit": request.limit}
            ]
            
            # Step 4: Execute query
            plans_cursor = subscription_plans_collection.aggregate(paginated_pipeline)
            plans_docs = await plans_cursor.to_list(length=None)
            
            # Step 5: Format response data
            plans_list = []
            for doc in plans_docs:
                # Skip soft-deleted plans if present
                if doc.get("deleted_at"):
                    continue
                
                # Validate and normalize type field from database
                doc_type = doc["type"]
                print(f"🔍 Processing document type: '{doc_type}' (type: {type(doc_type)})")
                
                if isinstance(doc_type, str):
                    # Map common variations to proper enum values
                    type_mapping = {
                        'trial': 'Trial',
                        'monthly': 'Monthly Club Membership',
                        'monthly club membership': 'Monthly Club Membership',
                        'club ownership': 'Club Ownership',
                        'club': 'Club Ownership',
                        'premium': 'Premium Membership',
                        'premium membership': 'Premium Membership',
                        'basic': 'Basic Membership',
                        'basic membership': 'Basic Membership',
                        'vip': 'VIP Membership',
                        'vip membership': 'VIP Membership'
                    }
                    
                    # Try exact match first, then case-insensitive match
                    if doc_type in type_mapping:
                        doc_type = type_mapping[doc_type]
                        print(f"✅ Document type mapped: '{doc.get('type')}' -> '{doc_type}'")
                    else:
                        # Try case-insensitive match
                        doc_type_lower = doc_type.lower()
                        if doc_type_lower in type_mapping:
                            doc_type = type_mapping[doc_type_lower]
                            print(f"✅ Document type mapped (case-insensitive): '{doc.get('type')}' -> '{doc_type}'")
                        else:
                            # If still not found, try to validate as is
                            try:
                                from .models import SubscriptionPlanType
                                SubscriptionPlanType(doc_type)
                                print(f"✅ Document type validated as enum: '{doc_type}'")
                            except ValueError:
                                print(f"❌ Warning: Invalid subscription plan type in database: {doc_type}")
                                # Skip this plan or use a default type
                                continue
                
                plan = SubscriptionPlan(
                    plan_id=str(doc["_id"]),
                    name=doc["name"],
                    thumbnail_url=doc.get("thumbnail_url"),
                    type=doc_type,
                    price=float(doc["price"]),
                    is_active=doc.get("is_active", True),
                    active_subscribers=doc.get("active_subscribers", 0),
                    created_at=doc["created_at"].isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at", ""),
                    updated_at=doc["updated_at"].isoformat() if isinstance(doc.get("updated_at"), datetime) else doc.get("updated_at"),
                    description=doc.get("description"),
                    features=doc.get("features", []),
                    duration_days=doc.get("duration_days")
                )
                plans_list.append(plan)
            
            # Step 6: Calculate pagination
            total_pages = (total_records + request.limit - 1) // request.limit
            pagination = SubscriptionPlanListPagination(
                current_page=request.page,
                total_pages=total_pages,
                total_records=total_records,
                records_per_page=request.limit,
                has_next=request.page < total_pages,
                has_previous=request.page > 1
            )
            
            # Step 7: Get summary statistics
            summary = await self._get_subscription_plans_summary(request)
            
            # Step 8: Get applied filters
            filters_applied = self._get_applied_filters(request)
            
            print(f"✅ Retrieved {len(plans_list)} subscription plans from {total_records} total")
            
            return SubscriptionPlanListResponse(
                success=True,
                message=f"Retrieved {len(plans_list)} subscription plans successfully",
                plans=plans_list,
                pagination=pagination,
                filters_applied=filters_applied,
                summary=summary
            )
            
        except Exception as e:
            print(f"❌ Error retrieving subscription plans list: {str(e)}")
            print(f"Request details: {request}")
            print(f"Pipeline: {pipeline}")
            raise Exception(f"Failed to retrieve subscription plans: {str(e)}")
    
    async def export_subscription_plans_csv(self, request: SubscriptionPlanCSVExportRequest, 
                                          admin_email: str) -> SubscriptionPlanCSVExportResponse:
        """
        Export subscription plans to CSV format
        
        Args:
            request: CSV export request with filters and field selection
            admin_email: Email of admin requesting the export
        
        Returns:
            SubscriptionPlanCSVExportResponse with CSV data
        """
        try:
            print(f"📊 Admin {admin_email} requesting CSV export for subscription plans")
            
            # Build aggregation pipeline (without pagination for export)
            pipeline = await self._build_subscription_plans_aggregation_pipeline(request)
            
            # Execute query to get all matching plans
            plans_cursor = subscription_plans_collection.aggregate(pipeline)
            plans_docs = await plans_cursor.to_list(length=None)
            
            # Generate CSV data
            csv_data = await self._generate_csv_data(plans_docs, request.fields)
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"subscription_plans_{timestamp}.csv"
            
            print(f"✅ CSV export completed: {len(plans_docs)} records exported")
            
            return SubscriptionPlanCSVExportResponse(
                success=True,
                message=f"Successfully exported {len(plans_docs)} subscription plans to CSV",
                csv_data=csv_data,
                filename=filename,
                total_records=len(plans_docs),
                fields_exported=request.fields
            )
            
        except Exception as e:
            print(f"❌ Error exporting subscription plans to CSV: {str(e)}")
            raise Exception(f"Failed to export subscription plans: {str(e)}")
    
    async def update_subscription_plan_status(self, request: SubscriptionPlanStatusUpdateRequest, 
                                            admin_email: str) -> SubscriptionPlanStatusUpdateResponse:
        """
        Update subscription plan active status
        
        Args:
            request: Status update request
            admin_email: Email of admin performing the update
        
        Returns:
            SubscriptionPlanStatusUpdateResponse with update details
        """
        try:
            print(f"🔄 Admin {admin_email} updating subscription plan {request.plan_id} status")
            
            # Get current plan
            plan = await subscription_plans_collection.find_one({"_id": ObjectId(request.plan_id)})
            if not plan:
                raise Exception("Subscription plan not found")
            
            previous_status = plan.get("is_active", True)
            
            # Update plan status
            result = await subscription_plans_collection.update_one(
                {"_id": ObjectId(request.plan_id)},
                {
                    "$set": {
                        "is_active": request.is_active,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count == 0:
                raise Exception("Failed to update subscription plan status")
            
            # Log admin action
            await self._log_admin_action(
                admin_email=admin_email,
                action="status_update",
                plan_id=request.plan_id,
                details={
                    "previous_status": previous_status,
                    "new_status": request.is_active
                }
            )
            
            print(f"✅ Subscription plan {request.plan_id} status updated successfully")
            
            return SubscriptionPlanStatusUpdateResponse(
                success=True,
                message="Subscription plan status updated successfully",
                plan_id=request.plan_id,
                previous_status=previous_status,
                new_status=request.is_active,
                updated_at=datetime.utcnow().isoformat()
            )
            
        except Exception as e:
            print(f"❌ Error updating subscription plan status: {str(e)}")
            raise Exception(f"Failed to update subscription plan status: {str(e)}")
    
    async def delete_subscription_plan(self, plan_id: str, admin_email: str) -> SubscriptionPlanDeleteResponse:
        """
        Soft delete subscription plan
        
        Args:
            plan_id: ID of plan to delete
            admin_email: Email of admin performing the deletion
        
        Returns:
            SubscriptionPlanDeleteResponse with deletion details
        """
        try:
            print(f"🗑️ Admin {admin_email} deleting subscription plan {plan_id}")
            
            # Check if plan exists
            plan = await subscription_plans_collection.find_one({"_id": ObjectId(plan_id)})
            if not plan:
                raise Exception("Subscription plan not found")
            
            # Check if plan has active subscriptions
            active_subscriptions = await subscriptions_collection.count_documents({
                "plan_id": plan_id,
                "status": "active"
            })
            
            if active_subscriptions > 0:
                raise Exception(f"Cannot delete plan with {active_subscriptions} active subscriptions")
            
            # Soft delete the plan
            result = await subscription_plans_collection.update_one(
                {"_id": ObjectId(plan_id)},
                {
                    "$set": {
                        "deleted_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count == 0:
                raise Exception("Failed to delete subscription plan")
            
            # Log admin action
            await self._log_admin_action(
                admin_email=admin_email,
                action="delete",
                plan_id=plan_id,
                details={"deleted_at": datetime.utcnow().isoformat()}
            )
            
            print(f"✅ Subscription plan {plan_id} deleted successfully")
            
            return SubscriptionPlanDeleteResponse(
                success=True,
                message="Subscription plan deleted successfully",
                plan_id=plan_id,
                deleted_at=datetime.utcnow().isoformat()
            )
            
        except Exception as e:
            print(f"❌ Error deleting subscription plan: {str(e)}")
            raise Exception(f"Failed to delete subscription plan: {str(e)}")
    
    async def get_subscription_plan_analytics(self, plan_id: str, admin_email: str) -> SubscriptionPlanAnalytics:
        """
        Get detailed analytics for a specific subscription plan
        
        Args:
            plan_id: ID of plan to analyze
            admin_email: Email of admin requesting analytics
        
        Returns:
            SubscriptionPlanAnalytics with detailed metrics
        """
        try:
            print(f"📈 Admin {admin_email} requesting analytics for subscription plan {plan_id}")
            
            # Get plan details
            plan = await subscription_plans_collection.find_one({"_id": ObjectId(plan_id)})
            if not plan:
                raise Exception("Subscription plan not found")
            
            # Get subscription statistics
            pipeline = [
                {"$match": {"plan_id": plan_id}},
                {
                    "$group": {
                        "_id": "$status",
                        "count": {"$sum": 1},
                        "total_revenue": {"$sum": "$amount"},
                        "avg_duration": {"$avg": {"$subtract": ["$end_date", "$start_date"]}}
                    }
                }
            ]
            
            stats_result = await subscriptions_collection.aggregate(pipeline).to_list(length=None)
            
            # Process statistics
            stats = {stat["_id"]: stat for stat in stats_result}
            
            total_subscriptions = sum(stat["count"] for stat in stats_result)
            active_subscriptions = stats.get("active", {}).get("count", 0)
            cancelled_subscriptions = stats.get("cancelled", {}).get("count", 0)
            expired_subscriptions = stats.get("expired", {}).get("count", 0)
            
            total_revenue = sum(stat.get("total_revenue", 0) for stat in stats_result)
            monthly_recurring_revenue = total_revenue / 12 if total_revenue > 0 else 0
            
            # Calculate churn rate
            churn_rate = 0
            if total_subscriptions > 0:
                churn_rate = ((cancelled_subscriptions + expired_subscriptions) / total_subscriptions) * 100
            
            # Calculate average subscription duration
            avg_duration_days = 0
            if stats_result:
                total_duration = sum(stat.get("avg_duration", 0) for stat in stats_result)
                avg_duration_days = total_duration / len(stats_result) / (1000 * 60 * 60 * 24)  # Convert to days
            
            print(f"✅ Analytics retrieved for subscription plan {plan_id}")
            
            return SubscriptionPlanAnalytics(
                plan_id=plan_id,
                plan_name=plan["name"],
                total_subscriptions=total_subscriptions,
                active_subscriptions=active_subscriptions,
                cancelled_subscriptions=cancelled_subscriptions,
                expired_subscriptions=expired_subscriptions,
                total_revenue=total_revenue,
                monthly_recurring_revenue=monthly_recurring_revenue,
                churn_rate=churn_rate,
                average_subscription_duration=avg_duration_days
            )
            
        except Exception as e:
            print(f"❌ Error retrieving subscription plan analytics: {str(e)}")
            raise Exception(f"Failed to retrieve analytics: {str(e)}")
    
    # ========================================
    # PRIVATE HELPER METHODS
    # ========================================
    
    async def _build_subscription_plans_aggregation_pipeline(self, request) -> List[Dict]:
        """
        Build MongoDB aggregation pipeline for subscription plans query
        """
        pipeline = []
        
        # Match stage - apply filters
        match_conditions = {}
        
        # Search filter
        if request.search:
            search_regex = {"$regex": request.search, "$options": "i"}
            match_conditions["$or"] = [
                {"name": search_regex},
                {"type": search_regex}
            ]
        
        # Type filter
        if request.type:
            match_conditions["type"] = request.type
        
        # Active status filter
        if request.is_active is not None:
            match_conditions["is_active"] = request.is_active
        
        # Price range filter
        if request.price_min is not None or request.price_max is not None:
            price_conditions = {}
            if request.price_min is not None:
                price_conditions["$gte"] = request.price_min
            if request.price_max is not None:
                price_conditions["$lte"] = request.price_max
            match_conditions["price"] = price_conditions
        
        # Exclude soft-deleted plans
        match_conditions["deleted_at"] = {"$exists": False}
        
        if match_conditions:
            pipeline.append({"$match": match_conditions})
        
        # Lookup stage - get active subscriber count
        pipeline.extend([
            {
                "$lookup": {
                    "from": "subscriptions",
                    "let": {"plan_id": {"$toString": "$_id"}},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$plan_id", "$$plan_id"]},
                                        {"$eq": ["$status", "active"]}
                                    ]
                                }
                            }
                        },
                        {"$count": "active_count"}
                    ],
                    "as": "active_subscribers_data"
                }
            },
            {
                "$addFields": {
                    "active_subscribers": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$active_subscribers_data.active_count", 0]},
                            0
                        ]
                    }
                }
            },
            {"$unset": "active_subscribers_data"}
        ])
        
        # Sort stage
        sort_field = request.sort_by.value
        sort_order = 1 if request.sort_order == SortOrder.ASC else -1
        
        # Handle special sorting for active_subscribers
        if sort_field == "active_subscribers":
            pipeline.append({"$sort": {"active_subscribers": sort_order}})
        else:
            pipeline.append({"$sort": {sort_field: sort_order}})
        
        return pipeline
    
    async def _get_subscription_plans_summary(self, request) -> Dict[str, Any]:
        """
        Get summary statistics for subscription plans
        """
        try:
            # Build base pipeline without pagination
            base_pipeline = await self._build_subscription_plans_aggregation_pipeline(request)
            
            # Get total plans count
            count_pipeline = base_pipeline + [{"$count": "total"}]
            count_result = await subscription_plans_collection.aggregate(count_pipeline).to_list(length=1)
            total_plans = count_result[0]["total"] if count_result else 0
            
            # Get active plans count
            active_pipeline = base_pipeline + [
                {"$match": {"is_active": True}},
                {"$count": "active"}
            ]
            active_result = await subscription_plans_collection.aggregate(active_pipeline).to_list(length=1)
            active_plans = active_result[0]["active"] if active_result else 0
            
            # Get total active subscribers
            subscribers_pipeline = base_pipeline + [
                {"$group": {"_id": None, "total_subscribers": {"$sum": "$active_subscribers"}}}
            ]
            subscribers_result = await subscription_plans_collection.aggregate(subscribers_pipeline).to_list(length=1)
            total_subscribers = subscribers_result[0]["total_subscribers"] if subscribers_result else 0
            
            # Get total revenue potential
            revenue_pipeline = base_pipeline + [
                {"$group": {"_id": None, "total_revenue": {"$sum": {"$multiply": ["$price", "$active_subscribers"]}}}}
            ]
            revenue_result = await subscription_plans_collection.aggregate(revenue_pipeline).to_list(length=1)
            total_revenue = revenue_result[0]["total_revenue"] if revenue_result else 0
            
            return {
                "total_plans": total_plans,
                "active_plans": active_plans,
                "inactive_plans": total_plans - active_plans,
                "total_active_subscribers": total_subscribers,
                "total_revenue_potential": total_revenue,
                "average_plan_price": total_revenue / total_subscribers if total_subscribers > 0 else 0
            }
            
        except Exception as e:
            print(f"⚠️ Error getting summary statistics: {str(e)}")
            return {
                "total_plans": 0,
                "active_plans": 0,
                "inactive_plans": 0,
                "total_active_subscribers": 0,
                "total_revenue_potential": 0,
                "average_plan_price": 0
            }
    
    def _get_applied_filters(self, request) -> Dict[str, Any]:
        """
        Get list of filters that were applied to the request
        """
        filters = {}
        
        if request.search:
            filters["search"] = request.search
        if request.type:
            filters["type"] = request.type.value
        if request.is_active is not None:
            filters["is_active"] = request.is_active
        if request.price_min is not None:
            filters["price_min"] = request.price_min
        if request.price_max is not None:
            filters["price_max"] = request.price_max
        
        return filters
    
    async def _generate_csv_data(self, plans_docs: List[Dict], fields: List[str]) -> str:
        """
        Generate CSV data from subscription plans documents
        """
        try:
            # Create CSV output
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write headers
            headers = []
            for field in fields:
                if field == "name":
                    headers.append("Name")
                elif field == "type":
                    headers.append("Type")
                elif field == "price":
                    headers.append("Price")
                elif field == "active_subscribers":
                    headers.append("Active Subscribers")
                elif field == "is_active":
                    headers.append("Status")
                elif field == "created_at":
                    headers.append("Created At")
                elif field == "updated_at":
                    headers.append("Updated At")
                elif field == "description":
                    headers.append("Description")
            
            writer.writerow(headers)
            
            # Write data rows
            for doc in plans_docs:
                row = []
                for field in fields:
                    if field == "name":
                        row.append(doc.get("name", ""))
                    elif field == "type":
                        row.append(doc.get("type", ""))
                    elif field == "price":
                        row.append(str(doc.get("price", 0)))
                    elif field == "active_subscribers":
                        row.append(str(doc.get("active_subscribers", 0)))
                    elif field == "is_active":
                        row.append("Active" if doc.get("is_active", True) else "Inactive")
                    elif field == "created_at":
                        created_at = doc.get("created_at")
                        if isinstance(created_at, datetime):
                            row.append(created_at.strftime("%Y-%m-%d %H:%M:%S"))
                        else:
                            row.append(str(created_at) if created_at else "")
                    elif field == "updated_at":
                        updated_at = doc.get("updated_at")
                        if isinstance(updated_at, datetime):
                            row.append(updated_at.strftime("%Y-%m-%d %H:%M:%S"))
                        else:
                            row.append(str(updated_at) if updated_at else "")
                    elif field == "description":
                        row.append(doc.get("description", ""))
                
                writer.writerow(row)
            
            return output.getvalue()
            
        except Exception as e:
            print(f"❌ Error generating CSV data: {str(e)}")
            raise Exception(f"Failed to generate CSV data: {str(e)}")
    
    async def _log_admin_action(self, admin_email: str, action: str, plan_id: str, details: Dict[str, Any]):
        """
        Log admin action for audit purposes
        """
        try:
            log_entry = {
                "admin_email": admin_email,
                "action": action,
                "plan_id": plan_id,
                "details": details,
                "timestamp": datetime.utcnow(),
                "service": self.service_name
            }
            
            await subscription_admin_logs_collection.insert_one(log_entry)
            print(f"✅ Admin action logged: {action} on plan {plan_id}")
            
        except Exception as e:
            print(f"⚠️ Failed to log admin action: {str(e)}")

# Create service instance
admin_subscription_plans_service = AdminSubscriptionPlansService()