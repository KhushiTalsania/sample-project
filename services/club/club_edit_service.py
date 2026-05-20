import stripe
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from .db import get_club_collection, get_user_collection
from .models import (
    ClubEditRequest, 
    ClubEditResponse, 
    PricingPlanEdit, 
    PricingPlanCreate,
    WhatsIncludedItem,
    SportInfo
)
from .utils import send_email_to_members

logger = logging.getLogger(__name__)

class ClubEditService:
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
        # Initialize Stripe with environment variable
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        if not stripe.api_key:
            logger.warning("⚠️ STRIPE_SECRET_KEY not found in environment variables")
        
    async def edit_club(self, request: ClubEditRequest, captain_id: str) -> ClubEditResponse:
        """
        Edit club details including pricing plans with Stripe integration
        """
        try:
            logger.info(f"🔧 Starting club edit for club_id: {request.club_id}, captain: {captain_id}")
            
            # Validate club ownership
            club = await self._validate_club_ownership(request.club_id, captain_id)
            if not club:
                return ClubEditResponse(
                    success=False,
                    message="Club not found or you don't have permission to edit this club",
                    club_id=request.club_id,
                    club_name="",
                    updated_fields=[],
                    pricing_plans_updated=0,
                    pricing_plans_added=0,
                    members_notified=0
                )
            
            # Check if this is a resubmission after temporary rejection
            is_resubmission = False
            admin_notification_sent = False
            
            if (club.get("status") == "rejected" and 
                club.get("is_club_reject_temporary") == True and 
                club.get("is_resubmit") == True):
                
                logger.info(f"🔄 Club is being resubmitted after temporary rejection: {club.get('name')}")
                is_resubmission = True
                
                # Send email notification to admin about resubmission
                admin_notification_sent = await self._notify_admin_about_resubmission(club)
            
            # Track what fields are being updated
            updated_fields = []
            pricing_plans_updated = 0
            pricing_plans_added = 0
            members_notified = 0
            
            # Prepare update data
            update_data = {"updated_at": datetime.utcnow()}
            
            # If this is a resubmission after temporary rejection, update status and flags
            if is_resubmission:
                update_data["status"] = "pending"
                update_data["is_club_reject_temporary"] = False
                update_data["is_resubmit"] = False
                update_data["resubmission_date"] = datetime.utcnow()
                updated_fields.extend(["status", "is_club_reject_temporary", "is_resubmit", "resubmission_date"])
                logger.info(f"🔄 Updating club status to pending for resubmission: {club.get('name')}")
            
            # Update basic club fields
            if request.name is not None:
                update_data["name"] = request.name
                updated_fields.append("name")
                
            if request.description is not None:
                update_data["description"] = request.description
                updated_fields.append("description")
                
            if request.sub_description is not None:
                update_data["sub_description"] = request.sub_description
                updated_fields.append("sub_description")
                
            if request.logo_url is not None:
                update_data["logo_url"] = request.logo_url
                updated_fields.append("logo_url")
                
            if request.whats_included is not None:
                update_data["whats_included"] = [item.dict() for item in request.whats_included]
                updated_fields.append("whats_included")
                
            if request.top_3_sports is not None:
                update_data["top_3_sports"] = [sport.dict() for sport in request.top_3_sports]
                updated_fields.append("top_3_sports")
            
            # Handle pricing plans updates
            if request.pricing_plans_edit or request.pricing_plans_add:
                pricing_result = await self._update_pricing_plans(
                    club, 
                    request.pricing_plans_edit or [], 
                    request.pricing_plans_add or []
                )
                pricing_plans_updated = pricing_result["updated"]
                pricing_plans_added = pricing_result["added"]
                update_data["pricing_plans"] = pricing_result["updated_plans"]
                updated_fields.append("pricing_plans")
            
            # Update club in database
            if update_data:
                await self.club_collection.update_one(
                    {"_id": club["_id"]},
                    {"$set": update_data}
                )
                logger.info(f"✅ Club updated successfully: {updated_fields}")
            
            # Send email notifications to members if pricing plans changed
            if "pricing_plans" in updated_fields:
                members_notified = await self._notify_members_about_pricing_changes(
                    club["_id"], 
                    club["name"]
                )
            
            # Prepare response message
            if is_resubmission:
                message = "Club updated and resubmitted for approval successfully"
                if admin_notification_sent:
                    message += " (Admin notification sent)"
                else:
                    message += " (Admin notification failed)"
            else:
                message = "Club updated successfully"
            
            return ClubEditResponse(
                success=True,
                message=message,
                club_id=str(club["_id"]),
                club_name=update_data.get("name", club["name"]),
                updated_fields=updated_fields,
                pricing_plans_updated=pricing_plans_updated,
                pricing_plans_added=pricing_plans_added,
                members_notified=members_notified
            )
            
        except Exception as e:
            logger.error(f"❌ Error editing club: {e}")
            import traceback
            traceback.print_exc()
            return ClubEditResponse(
                success=False,
                message=f"Failed to edit club: {str(e)}",
                club_id=request.club_id,
                club_name="",
                updated_fields=[],
                pricing_plans_updated=0,
                pricing_plans_added=0,
                members_notified=0
            )
    
    async def _validate_club_ownership(self, club_id: str, captain_id: str) -> Optional[Dict]:
        """Validate that the captain owns the club"""
        try:
            logger.info(f"🔍 Validating club ownership - club_id: {club_id}, captain_id: {captain_id}")
            
            # First, let's check if the club exists at all (without captain filter)
            club_exists = await self.club_collection.find_one({
                "name_based_id": club_id,
                "is_active": True
            })
            
            if not club_exists:
                # Try by ObjectId
                try:
                    club_exists = await self.club_collection.find_one({
                        "_id": ObjectId(club_id),
                        "is_active": True
                    })
                except:
                    pass
            
            # If still not found, try without is_active filter
            if not club_exists:
                club_exists = await self.club_collection.find_one({
                    "name_based_id": club_id
                })
                
                if not club_exists:
                    try:
                        club_exists = await self.club_collection.find_one({
                            "_id": ObjectId(club_id)
                        })
                    except:
                        pass
            
            if not club_exists:
                logger.warning(f"❌ Club not found: {club_id}")
                # Let's also check if any club exists with this name_based_id (even if inactive)
                any_club = await self.club_collection.find_one({"name_based_id": club_id})
                if any_club:
                    logger.warning(f"🔍 Club exists but is inactive - is_active: {any_club.get('is_active')}, captain_id: {any_club.get('captain_id')}")
                else:
                    logger.warning(f"🔍 No club found with name_based_id: {club_id}")
                return None
            
            # Check if club is active
            if not club_exists.get('is_active', True):
                logger.warning(f"❌ Club is inactive - is_active: {club_exists.get('is_active')}")
                return None
            
            logger.info(f"✅ Club found: {club_exists.get('name')} - Captain ID: {club_exists.get('captain_id')} (type: {type(club_exists.get('captain_id'))})")
            logger.info(f"🔍 Comparing captain IDs - Expected: '{captain_id}' (type: {type(captain_id)}) vs Found: '{club_exists.get('captain_id')}' (type: {type(club_exists.get('captain_id'))})")
            
            # Check if captain IDs match (try both string and ObjectId comparisons)
            stored_captain_id = club_exists.get('captain_id')
            captain_match = False
            
            # Direct string comparison
            if str(stored_captain_id) == str(captain_id):
                captain_match = True
                logger.info(f"✅ Captain ID match found (string comparison)")
            
            # ObjectId comparison
            elif stored_captain_id and captain_id:
                try:
                    if ObjectId(stored_captain_id) == ObjectId(captain_id):
                        captain_match = True
                        logger.info(f"✅ Captain ID match found (ObjectId comparison)")
                except Exception as e:
                    logger.warning(f"⚠️ ObjectId comparison failed: {e}")
            
            if not captain_match:
                logger.warning(f"❌ Captain ownership denied - Captain ID mismatch. Expected: '{captain_id}', Found: '{stored_captain_id}'")
                # Let's also check what clubs this captain actually owns
                captain_clubs = await self.club_collection.find({
                    "captain_id": captain_id,
                    "is_active": True
                }).to_list(length=5)
                logger.info(f"🔍 Captain {captain_id} owns {len(captain_clubs)} clubs:")
                for club in captain_clubs:
                    logger.info(f"  - {club.get('name')} (ID: {club.get('name_based_id')})")
                return None
            
            logger.info(f"✅ Captain ownership verified for club: {club_exists.get('name')}")
            return club_exists
            
        except Exception as e:
            logger.error(f"Error validating club ownership: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _update_pricing_plans(
        self, 
        club: Dict, 
        plans_to_edit: List[PricingPlanEdit], 
        plans_to_add: List[PricingPlanCreate]
    ) -> Dict[str, Any]:
        """Update and add pricing plans with Stripe integration"""
        try:
            current_plans = club.get("pricing_plans", [])
            updated_plans = current_plans.copy()
            updated_count = 0
            added_count = 0
            
            logger.info(f"🔧 Updating pricing plans - Current plans: {len(current_plans)}")
            logger.info(f"🔧 Plans to edit: {len(plans_to_edit)}, Plans to add: {len(plans_to_add)}")
            
            # Update existing pricing plans
            for edit_plan in plans_to_edit:
                logger.info(f"🔧 Processing edit plan: {edit_plan.frequency} - ${edit_plan.price} {edit_plan.currency}")
                
                for i, existing_plan in enumerate(updated_plans):
                    if existing_plan.get("frequency") == edit_plan.frequency:
                        logger.info(f"🔧 Found matching plan to update: {existing_plan}")
                        
                        # Check if we have a valid existing price ID
                        existing_price_id = existing_plan.get("stripe_price_id")
                        if existing_price_id and existing_price_id != "string":
                            try:
                                # Update Stripe price
                                stripe_price_id = await self._update_stripe_price(
                                    existing_price_id,
                                    edit_plan.price,
                                    edit_plan.currency
                                )
                                logger.info(f"✅ Updated Stripe price: {existing_price_id} -> {stripe_price_id}")
                            except Exception as e:
                                logger.error(f"❌ Failed to update Stripe price: {e}")
                                # Continue with the update even if Stripe fails
                                stripe_price_id = existing_price_id
                        else:
                            logger.warning(f"⚠️ No valid existing price ID found, keeping existing: {existing_price_id}")
                            stripe_price_id = existing_price_id
                        
                        # Update the plan in our list
                        updated_plans[i] = {
                            **existing_plan,
                            "price": edit_plan.price,
                            "currency": edit_plan.currency,
                            "stripe_price_id": stripe_price_id,
                            "updated_at": datetime.utcnow()
                        }
                        updated_count += 1
                        logger.info(f"✅ Updated plan: {updated_plans[i]}")
                        break
                else:
                    logger.warning(f"⚠️ No existing plan found for frequency: {edit_plan.frequency}")
            
            # Add new pricing plans
            for new_plan in plans_to_add:
                logger.info(f"🔧 Processing new plan: {new_plan.frequency} - ${new_plan.price} {new_plan.currency}")
                
                # Create Stripe price
                stripe_product_id = club.get("stripe_product_id")
                if not stripe_product_id:
                    # Create Stripe product if it doesn't exist
                    stripe_product_id = await self._create_stripe_product(club["name"])
                    await self.club_collection.update_one(
                        {"_id": club["_id"]},
                        {"$set": {"stripe_product_id": stripe_product_id}}
                    )
                
                try:
                    stripe_price_id = await self._create_stripe_price(
                        stripe_product_id,
                        new_plan.price,
                        new_plan.currency,
                        new_plan.frequency
                    )
                    logger.info(f"✅ Created new Stripe price: {stripe_price_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to create Stripe price: {e}")
                    # Continue with a placeholder
                    stripe_price_id = f"price_placeholder_{datetime.utcnow().timestamp()}"
                
                # Add new plan to our list
                new_plan_data = {
                    "frequency": new_plan.frequency,
                    "price": new_plan.price,
                    "currency": new_plan.currency,
                    "stripe_product_id": stripe_product_id,
                    "stripe_price_id": stripe_price_id,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
                updated_plans.append(new_plan_data)
                added_count += 1
                logger.info(f"✅ Added new plan: {new_plan_data}")
            
            logger.info(f"✅ Pricing plans update complete - Updated: {updated_count}, Added: {added_count}")
            return {
                "updated_plans": updated_plans,
                "updated": updated_count,
                "added": added_count
            }
            
        except Exception as e:
            logger.error(f"Error updating pricing plans: {e}")
            raise e
    
    async def _update_stripe_price(self, existing_price_id: str, new_price: float, currency: str) -> str:
        """Update existing Stripe price"""
        try:
            if not existing_price_id or existing_price_id == "string":
                raise ValueError("No valid existing price ID provided")
            
            logger.info(f"🔧 Updating Stripe price: {existing_price_id} to ${new_price} {currency}")
            
            # Get the existing price to extract product and interval info
            existing_price = stripe.Price.retrieve(existing_price_id)
            product_id = existing_price.product
            interval = existing_price.recurring.interval if existing_price.recurring else "month"
            
            # Archive the old price
            stripe.Price.modify(existing_price_id, active=False)
            logger.info(f"✅ Archived old price: {existing_price_id}")
            
            # Create new price with updated amount
            new_price_obj = stripe.Price.create(
                unit_amount=int(new_price * 100),  # Convert to cents
                currency=currency.lower(),
                product=product_id,
                recurring={"interval": interval}
            )
            
            logger.info(f"✅ Created new Stripe price: {new_price_obj.id}")
            return new_price_obj.id
            
        except Exception as e:
            logger.error(f"Error updating Stripe price: {e}")
            raise e
    
    async def _create_stripe_price(self, product_id: str, price: float, currency: str, frequency: str) -> str:
        """Create new Stripe price"""
        try:
            price_obj = stripe.Price.create(
                unit_amount=int(price * 100),  # Convert to cents
                currency=currency.lower(),
                product=product_id,
                recurring={"interval": self._get_stripe_interval_from_frequency(frequency)}
            )
            
            logger.info(f"✅ Created new Stripe price: {price_obj.id}")
            return price_obj.id
            
        except Exception as e:
            logger.error(f"Error creating Stripe price: {e}")
            raise e
    
    async def _create_stripe_product(self, club_name: str) -> str:
        """Create Stripe product for the club"""
        try:
            product = stripe.Product.create(
                name=f"{club_name} - Club Membership",
                description=f"Membership for {club_name} betting club"
            )
            
            logger.info(f"✅ Created Stripe product: {product.id}")
            return product.id
            
        except Exception as e:
            logger.error(f"Error creating Stripe product: {e}")
            raise e
    
    def _get_stripe_interval(self, price_id: str) -> str:
        """Get Stripe interval from existing price"""
        try:
            price = stripe.Price.retrieve(price_id)
            return price.recurring.interval
        except:
            return "month"  # Default fallback
    
    def _get_stripe_interval_from_frequency(self, frequency: str) -> str:
        """Convert frequency to Stripe interval"""
        frequency_map = {
            "daily": "day",
            "weekly": "week",
            "monthly": "month",
            "quarterly": "month",  # Stripe doesn't have quarterly, use 3 months
            "yearly": "year",
            "lifetime": "month"  # Lifetime will be handled as one-time payment
        }
        return frequency_map.get(frequency.lower(), "month")
    
    async def _notify_members_about_pricing_changes(self, club_id: ObjectId, club_name: str) -> int:
        """Send email notifications to all members about pricing changes"""
        try:
            # Get the club to access member arrays
            club = await self.club_collection.find_one({"_id": club_id})
            if not club:
                logger.warning("Club not found for member notification")
                return 0
            
            # Collect all members from both arrays
            all_members = []
            
            # Add paid members
            paid_members = club.get("paid_members", [])
            for member in paid_members:
                if member.get("status") == "active" and member.get("membership_status") == "active":
                    all_members.append({
                        "email": member.get("email"),
                        "full_name": member.get("full_name"),
                        "membership_type": "paid"
                    })
            
            # Add trial members
            trial_members = club.get("members", [])
            for member in trial_members:
                if member.get("status") == "active" and member.get("membership_status") == "active":
                    all_members.append({
                        "email": member.get("email"),
                        "full_name": member.get("full_name"),
                        "membership_type": "trial"
                    })
            
            if not all_members:
                logger.info("No active members found to notify")
                return 0
            
            logger.info(f"🔔 Notifying {len(all_members)} members about pricing changes")
            
            # Send email to each member
            notification_count = 0
            for member in all_members:
                try:
                    email = member.get("email")
                    if email:
                        await send_email_to_members(
                            to_email=email,
                            subject=f"Pricing Update - {club_name}",
                            message=f"""
                            <h2>Pricing Plan Updated</h2>
                            <p>Dear {member.get('full_name', 'Member')},</p>
                            <p>The pricing plans for <strong>{club_name}</strong> have been updated.</p>
                            <p>Please check the club details for the latest pricing information.</p>
                            <p>Thank you for being a valued member!</p>
                            <br>
                            <p>Best regards,<br>The {club_name} Team</p>
                            """
                        )
                        notification_count += 1
                        logger.info(f"✅ Sent notification to {email}")
                except Exception as e:
                    logger.error(f"Failed to send notification to {member.get('email')}: {e}")
                    continue
            
            logger.info(f"✅ Sent pricing change notifications to {notification_count} members")
            return notification_count
            
        except Exception as e:
            logger.error(f"Error notifying members about pricing changes: {e}")
            return 0
    
    async def _notify_admin_about_resubmission(self, club: Dict) -> bool:
        """Send email notification to admin about club resubmission after temporary rejection"""
        try:
            from core.utils.email_service import send_email
            
            club_name = club.get("name", "Unknown Club")
            club_id = str(club.get("_id", ""))
            captain_name = club.get("captain_name", "Unknown Captain")
            captain_email = club.get("captain_email", "Unknown Email")
            
            # Get admin email from environment or use a default
            admin_email = os.getenv("ADMIN_EMAIL", "tj@mailinator.com")
            
            subject = f"Club Resubmission - {club_name}"
            message = f"""
            <h2>Club Resubmitted for Review</h2>
            <p>Dear Admin,</p>
            <p>A club has been resubmitted for approval after being temporarily rejected:</p>
            
            <h3>Club Details:</h3>
            <ul>
                <li><strong>Club Name:</strong> {club_name}</li>
                <li><strong>Club ID:</strong> {club_id}</li>
                <li><strong>Captain Name:</strong> {captain_name}</li>
                <li><strong>Captain Email:</strong> {captain_email}</li>
                <li><strong>Resubmission Date:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</li>
            </ul>
            
            <p>The captain has made the requested changes and resubmitted the club for your review.</p>
            <p>Please review the club details and approve or reject it accordingly.</p>
            
            <p>Thank you for your attention.</p>
            <br>
            <p>Best regards,<br>Club Management System</p>
            """
            
            await send_email(
                to_email=admin_email,
                subject=subject,
                message=message
            )
            
            logger.info(f"✅ Admin notification sent for club resubmission: {club_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to send admin notification for resubmission: {e}")
            return False

# Service instance
def get_club_edit_service() -> ClubEditService:
    return ClubEditService()
