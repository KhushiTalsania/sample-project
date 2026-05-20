from typing import Optional, List, Dict
from datetime import datetime, timezone
from bson import ObjectId
from .db import get_club_collection, get_user_collection
from .models import ClubStep3UpdateRequest, ClubStep3Response, ClubStep3Document, ClubStatus
from .auth import get_current_captain, verify_club_ownership
from .id_utils import is_valid_name_based_id
from .stripe_service import StripeService
from services.admin.db import get_admin_collection
import logging

logger = logging.getLogger(__name__)

class ClubStep3Service:
    """Service for managing club step 3 (pricing setup)"""
    
    async def get_admin_id_for_tj(self) -> Optional[str]:
        """Get admin_id for tj@mailinator.com"""
        try:
            admin_collection = get_admin_collection()
            admin = await admin_collection.find_one({"email": "tj@mailinator.com"})
            if admin:
                return str(admin["_id"])
            else:
                logger.warning("Admin tj@mailinator.com not found in database")
                return None
        except Exception as e:
            logger.error(f"Error getting admin_id for tj@mailinator.com: {e}")
            return None
    
    async def update_club_step3(self, request: ClubStep3UpdateRequest, captain_id: str, admin_id: str = None) -> Optional[dict]:
        """Update club with step 3 (pricing setup)"""
        try:
            logger.info(f"Starting club step 3 update for club_id: {request.club_id}, captain_id: {captain_id}")
            club_collection = get_club_collection()
            
            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(request.club_id):
                logger.info(f"Searching by name_based_id: {request.club_id}")
                # Search by name_based_id
                club = await club_collection.find_one({
                    "name_based_id": request.club_id,
                    "captain_id": captain_id
                })
                if not club:
                    logger.warning(f"Club not found by name_based_id: {request.club_id} for captain: {captain_id}")
                    raise ValueError("Club not found or you don't have permission to update it")
                club_object_id = club["_id"]
                logger.info(f"Found club by name_based_id: {club.get('name', 'Unknown')}")
            else:
                logger.info(f"Searching by ObjectId: {request.club_id}")
                # Try to validate as ObjectId
                try:
                    club_object_id = ObjectId(request.club_id)
                except Exception as e:
                    logger.error(f"Invalid ObjectId format: {request.club_id}, error: {e}")
                    raise ValueError("Invalid club ID format")
                
                # Check if club exists and belongs to the captain
                club = await club_collection.find_one({
                    "_id": club_object_id,
                    "captain_id": captain_id
                })
            
            if not club:
                logger.warning(f"Club not found or captain mismatch for club_id: {request.club_id}, captain_id: {captain_id}")
                raise ValueError("Club not found or you don't have permission to update it")
            
            logger.info(f"Club found: {club.get('name', 'Unknown')}, current step: {club.get('club_complete_step', 0)}")
            
            # Check if club is at step 2 (required for step 3)
            if club.get("club_complete_step", 0) < 2:
                logger.warning(f"Club {club.get('name', 'Unknown')} is at step {club.get('club_complete_step', 0)}, cannot proceed to step 3")
                raise ValueError("Club must complete step 2 (inclusions and sports) before setting up pricing")
            
            # Validate pricing plans
            if not request.pricing_plans:
                logger.warning("No pricing plans provided")
                raise ValueError("At least one pricing plan is required")
            
            # Check for duplicate frequencies
            frequencies = [plan.frequency for plan in request.pricing_plans]
            if len(frequencies) != len(set(frequencies)):
                logger.warning(f"Duplicate pricing frequencies detected: {frequencies}")
                raise ValueError("Duplicate pricing frequencies are not allowed")
            
            # Validate each plan
            for i, plan in enumerate(request.pricing_plans):
                logger.info(f"Validating plan {i+1}: frequency={plan.frequency}, price={plan.price}, currency={plan.currency}")
                if plan.price <= 0:
                    raise ValueError(f"Plan {i+1}: Price must be greater than 0")
                if plan.currency not in ["USD", "EUR", "GBP"]:
                    logger.warning(f"Plan {i+1}: Currency {plan.currency} may not be supported by Stripe")
            
            logger.info(f"Validating {len(request.pricing_plans)} pricing plans...")
            
            # Create step 3 document
            step3_doc = ClubStep3Document(
                pricing_plans=request.pricing_plans,
                club_complete_step=3,
                updated_at=datetime.now(timezone.utc)
            )
            
            logger.info("Creating Stripe products and prices...")
            
            try:
                # Test Stripe connection first
                logger.info("Testing Stripe connection...")
                stripe_connected = await StripeService.test_stripe_connection()
                if not stripe_connected:
                    raise Exception("Stripe API connection failed")
                
                # Get admin_id for tj@mailinator.com
                if not admin_id:
                    admin_id = await self.get_admin_id_for_tj()
                    logger.info(f"Retrieved admin_id for tj@mailinator.com: {admin_id}")
                
                # Create Stripe products and prices
                club_name = club.get("name", "Unknown Club")
                logger.info(f"Calling StripeService.create_pricing_plans_for_club with club_id: {club_object_id}, club_name: {club_name}")
                
                updated_pricing_plans = await StripeService.create_pricing_plans_for_club(
                    str(club_object_id), 
                    club_name, 
                    captain_id, 
                    [plan.model_dump() for plan in request.pricing_plans],
                    admin_id
                )
                
                logger.info(f"Successfully created {len(updated_pricing_plans)} Stripe pricing plans")
                logger.info(f"Updated plans: {updated_pricing_plans}")
                
                # Update club with step 3 data including Stripe information
                result = await club_collection.update_one(
                    {"_id": club_object_id},
                    {
                        "$set": {
                            "pricing_plans": updated_pricing_plans,
                            "club_complete_step": 3,
                            "has_stripe_product": True,
                            "has_stripe_price": True,
                            "stripe_product_id": updated_pricing_plans[0].get("stripe_product_id") if updated_pricing_plans else None,
                            "updated_at": datetime.now(timezone.utc)
                        }
                    }
                )
                
                # Update club count for captain since step changed
                if result.modified_count > 0:
                    try:
                        from .db import update_club_count_on_step_change
                        await update_club_count_on_step_change(captain_id, str(club_object_id), 3)
                        logger.info(f"✅ Club count updated for captain {captain_id} after step 3 completion")
                    except Exception as count_error:
                        logger.warning(f"⚠️ Could not update club count for captain {captain_id}: {count_error}")
                
            except Exception as stripe_error:
                logger.error(f"Failed to create Stripe products/prices: {stripe_error}")
                logger.error(f"Stripe error details: {type(stripe_error).__name__}: {str(stripe_error)}")
                import traceback
                logger.error(f"Stripe error traceback: {traceback.format_exc()}")
                
                # Fallback: update without Stripe integration
                logger.info("Falling back to database-only update...")
                result = await club_collection.update_one(
                    {"_id": club_object_id},
                    {
                        "$set": {
                            "pricing_plans": [plan.model_dump() for plan in request.pricing_plans],
                            "club_complete_step": 3,
                            "has_stripe_product": False,
                            "has_stripe_price": False,
                            "updated_at": datetime.now(timezone.utc)
                        }
                    }
                )
            
            if result.modified_count > 0:
                logger.info(f"Club updated successfully, modified count: {result.modified_count}")
                # Get updated club
                updated_club = await club_collection.find_one({"_id": club_object_id})
                
                if not updated_club:
                    logger.error("Failed to retrieve updated club after update")
                    return None
                
                logger.info("Building response...")
                
                # Build response
                # Handle status conversion safely
                status_value = updated_club.get("status", "pending")
                try:
                    if isinstance(status_value, str):
                        # Convert to proper case for enum
                        if status_value.lower() == "pending":
                            status_enum = ClubStatus.PENDING
                        elif status_value.lower() == "approved":
                            status_enum = ClubStatus.APPROVED
                        elif status_value.lower() == "rejected":
                            status_enum = ClubStatus.REJECT
                        else:
                            status_enum = ClubStatus.PENDING  # Default
                    else:
                        status_enum = ClubStatus.PENDING
                except Exception as e:
                    logger.warning(f"Status conversion failed, using default: {e}")
                    status_enum = ClubStatus.PENDING  # Fallback
                
                # Safely handle whats_included and top_3_sports
                whats_included = []
                try:
                    for inclusion in updated_club.get("whats_included", []):
                        whats_included.append(ClubInclusionSelection(**inclusion))
                except Exception as e:
                    logger.warning(f"Error processing whats_included: {e}")
                    whats_included = []
                
                top_3_sports = []
                try:
                    for sport in updated_club.get("top_3_sports", []):
                        top_3_sports.append(ClubSportSelection(**sport))
                except Exception as e:
                    logger.warning(f"Error processing top_3_sports: {e}")
                    top_3_sports = []
                
                # Get Stripe information from updated club
                has_stripe_product = updated_club.get("has_stripe_product", False)
                has_stripe_price = updated_club.get("has_stripe_price", False)
                stripe_product_id = updated_club.get("stripe_product_id")
                total_plans = len(updated_club.get("pricing_plans", []))
                
                # Convert pricing plans to include Stripe IDs
                enhanced_pricing_plans = []
                for plan in updated_club.get("pricing_plans", []):
                    enhanced_plan = {
                        "frequency": plan.get("frequency"),
                        "price": plan.get("price"),
                        "currency": plan.get("currency", "USD"),
                        "stripe_product_id": plan.get("stripe_product_id"),
                        "stripe_price_id": plan.get("stripe_price_id")
                    }
                    enhanced_pricing_plans.append(enhanced_plan)
                
                logger.info(f"Enhanced pricing plans: {enhanced_pricing_plans}")
                logger.info(f"Stripe product ID: {stripe_product_id}")
                logger.info(f"Has Stripe product: {has_stripe_product}")
                logger.info(f"Has Stripe price: {has_stripe_price}")
                
                response = ClubStep3Response(
                    id=str(updated_club["_id"]),
                    name=updated_club["name"],
                    name_based_id=updated_club.get("name_based_id", ""),
                    description=updated_club["description"],
                    sub_description=updated_club.get("sub_description"),
                    logo_url=updated_club.get("logo_url"),
                    status=status_enum,
                    club_complete_step=updated_club.get("club_complete_step", 3),
                    captain_id=updated_club["captain_id"],
                    whats_included=whats_included,
                    top_3_sports=top_3_sports,
                    pricing_plans=enhanced_pricing_plans,
                    has_stripe_product=has_stripe_product,
                    has_stripe_price=has_stripe_price,
                    stripe_product_id=stripe_product_id,
                    total_plans=total_plans,
                    created_at=updated_club["created_at"],
                    updated_at=updated_club["updated_at"]
                )
                
                logger.info("Response built successfully")
                logger.info(f"Final response data: {response.model_dump()}")
                
                # Return dictionary representation instead of Pydantic model
                return response.model_dump()
            
            else:
                logger.warning("No changes made to club during update")
                return None
            
        except ValueError as e:
            # Re-raise ValueError for validation errors
            logger.warning(f"Validation error in club step 3 update: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error updating club step 3: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def get_club_step3_status(self, club_id: str, captain_id: str) -> Optional[dict]:
        """Get club step 3 completion status"""
        try:
            club_collection = get_club_collection()
            
            # Check if club_id is a name_based_id or ObjectId
            if is_valid_name_based_id(club_id):
                # Search by name_based_id
                club = await club_collection.find_one({
                    "name_based_id": club_id,
                    "captain_id": captain_id
                })
            else:
                # Try to validate as ObjectId
                try:
                    club_object_id = ObjectId(club_id)
                    club = await club_collection.find_one({
                        "_id": club_object_id,
                        "captain_id": captain_id
                    })
                except Exception:
                    raise ValueError("Invalid club ID format")
            
            if not club:
                return None
            
            return {
                "club_id": str(club["_id"]),
                "name": club["name"],
                "name_based_id": club.get("name_based_id", ""),
                "club_complete_step": club.get("club_complete_step", 0),
                "pricing_plans": club.get("pricing_plans", []),
                "can_proceed_to_step3": club.get("club_complete_step", 0) >= 2,
                "step3_completed": club.get("club_complete_step", 0) >= 3
            }
            
        except Exception as e:
            logger.error(f"Error getting club step 3 status: {e}")
            return None
    
    async def get_club_by_name_based_id(self, name_based_id: str) -> Optional[dict]:
        """Get club by name_based_id"""
        try:
            if not is_valid_name_based_id(name_based_id):
                raise ValueError("Invalid name_based_id format")
            
            club_collection = get_club_collection()
            club = await club_collection.find_one({"name_based_id": name_based_id})
            
            if not club:
                return None
            
            return {
                "club_id": str(club["_id"]),
                "name": club["name"],
                "name_based_id": club.get("name_based_id", ""),
                "description": club.get("description", ""),
                "sub_description": club.get("sub_description"),
                "logo_url": club.get("logo_url"),
                "status": club.get("status", "pending"),
                "club_complete_step": club.get("club_complete_step", 0),
                "captain_id": club["captain_id"],
                "whats_included": club.get("whats_included", []),
                "top_3_sports": club.get("top_3_sports", []),
                "pricing_plans": club.get("pricing_plans", []),
                "created_at": club.get("created_at"),
                "updated_at": club.get("updated_at")
            }
            
        except Exception as e:
            logger.error(f"Error getting club by name_based_id: {e}")
            return None

# Create service instance
club_step3_service = ClubStep3Service()
