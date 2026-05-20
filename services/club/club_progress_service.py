from typing import Optional, List, Dict, Any
from datetime import datetime
from bson import ObjectId
import logging

from .db import get_club_collection, get_user_collection
from .models import ClubStatus

logger = logging.getLogger(__name__)

async def get_captain_club_progress(captain_id: str) -> Optional[Dict[str, Any]]:
    """
    Get comprehensive club creation progress for a captain
    
    Returns a detailed object showing all completed steps with their information
    """
    try:
        club_collection = get_club_collection()
        user_collection = get_user_collection()
        
        # Verify captain exists
        captain_object_id = ObjectId(captain_id)
        captain = await user_collection.find_one({"_id": captain_object_id})
        
        if not captain:
            logger.warning(f"Captain not found: {captain_id}")
            return None
        
        # Get all clubs for this captain
        clubs = await club_collection.find({"captain_id": captain_id}).sort("created_at", -1).to_list(length=None)
        
        if not clubs:
            logger.info(f"No clubs found for captain: {captain_id}")
            return None
        
        # Prepare captain info
        captain_info = {
            "id": captain_id,
            "full_name": captain.get("full_name", ""),
            "name_based_id": captain.get("name_based_id", ""),
            "email": captain.get("email", ""),
            "total_clubs": len(clubs)
        }
        
        # Process each club and its completed steps
        clubs_progress = []
        
        for club in clubs:
            club_progress = {
                "club_id": str(club["_id"]),
                "name": club.get("name", ""),
                "name_based_id": club.get("name_based_id", ""),
                "description": club.get("description", ""),
                "sub_description": club.get("sub_description"),
                "logo_url": club.get("logo_url"),
                "banner_url": club.get("banner_url"),
                "status": club.get("status", "pending"),
                "club_complete_step": club.get("club_complete_step", 0),
                "created_at": club.get("created_at"),
                "updated_at": club.get("updated_at"),
                "completed_steps": []
            }
            
            # Step 1: Basic club information (always present if club exists)
            step1_info = {
                "step_number": 1,
                "step_name": "Club Basic Information",
                "completed": True,
                "completed_at": club.get("created_at"),
                "data": {
                    "name": club.get("name", ""),
                    "description": club.get("description", ""),
                    "sub_description": club.get("sub_description"),
                    "logo_url": club.get("logo_url"),
                    "banner_url": club.get("banner_url"),
                    "captain_details": club.get("captain_details", {})
                }
            }
            club_progress["completed_steps"].append(step1_info)
            
            # Step 2: What's included + Top 3 sports
            if club.get("club_complete_step", 0) >= 2:
                step2_info = {
                    "step_number": 2,
                    "step_name": "What's Included + Top 3 Sports",
                    "completed": True,
                    "completed_at": club.get("updated_at"),
                    "data": {
                        "whats_included": club.get("whats_included", []),
                        "top_3_sports": club.get("top_3_sports", [])
                    }
                }
                club_progress["completed_steps"].append(step2_info)
            else:
                step2_info = {
                    "step_number": 2,
                    "step_name": "What's Included + Top 3 Sports",
                    "completed": False,
                    "completed_at": None,
                    "data": None
                }
                club_progress["completed_steps"].append(step2_info)
            
            # Step 3: Pricing setup
            if club.get("club_complete_step", 0) >= 3:
                step3_info = {
                    "step_number": 3,
                    "step_name": "Pricing Setup",
                    "completed": True,
                    "completed_at": club.get("updated_at"),
                    "data": {
                        "pricing_plans": club.get("pricing_plans", []),
                        "has_stripe_product": club.get("has_stripe_product", False),
                        "has_stripe_price": club.get("has_stripe_price", False),
                        "stripe_product_id": club.get("stripe_product_id"),
                        "total_plans": len(club.get("pricing_plans", []))
                    }
                }
                club_progress["completed_steps"].append(step3_info)
            else:
                step3_info = {
                    "step_number": 3,
                    "step_name": "Pricing Setup",
                    "completed": False,
                    "completed_at": None,
                    "data": None
                }
                club_progress["completed_steps"].append(step3_info)
            
            # Step 4: Moderator setup
            if club.get("club_complete_step", 0) >= 4:
                step4_info = {
                    "step_number": 4,
                    "step_name": "Moderator Setup",
                    "completed": True,
                    "completed_at": club.get("updated_at"),
                    "data": {
                        "moderator_emails": club.get("moderator_emails", []),
                        "moderator_count": club.get("moderator_count", 0),
                        "free_moderators": club.get("free_moderators", 0),
                        "paid_moderators": club.get("paid_moderators", 0),
                        "additional_moderator_price": club.get("additional_moderator_price",9.95),
                        "additional_moderator_currency": club.get("additional_moderator_currency"),
                        "total_additional_moderator_pricing": club.get("total_additional_moderator_pricing", 0),
                        "stripe_product_id": club.get("stripe_product_id"),
                        "stripe_price_id": club.get("stripe_price_id"),
                        "moderator_invitations": club.get("moderator_invitations", [])
                    }
                }
                club_progress["completed_steps"].append(step4_info)
            else:
                step4_info = {
                    "step_number": 4,
                    "step_name": "Moderator Setup",
                    "completed": False,
                    "completed_at": None,
                    "data": None
                }
                club_progress["completed_steps"].append(step4_info)
            
            clubs_progress.append(club_progress)
        
        # Calculate overall progress
        total_steps = 4
        total_possible_completions = len(clubs) * total_steps
        actual_completions = sum(min(c.get("club_complete_step", 0), total_steps) for c in clubs)
        overall_progress = {
            "total_steps": total_steps,
            "total_clubs": len(clubs),
            "total_possible_completions": total_possible_completions,
            "actual_completions": actual_completions,
            "completion_percentage": round((actual_completions / total_possible_completions) * 100, 2) if total_possible_completions > 0 else 0
        }
        
        # Prepare final response
        response_data = {
            "captain": captain_info,
            "overall_progress": overall_progress,
            "clubs": clubs_progress
        }
        
        logger.info(f"Retrieved progress for captain {captain_id}: {len(clubs)} clubs, {actual_completions}/{total_possible_completions} steps completed")
        return response_data
        
    except Exception as e:
        logger.error(f"Error getting captain club progress: {e}")
        return None

async def get_club_step_details(club_id: str, step_number: int) -> Optional[Dict[str, Any]]:
    """
    Get detailed information for a specific step of a club
    
    This is a helper function to get step-specific details
    """
    try:
        club_collection = get_club_collection()
        club_object_id = ObjectId(club_id)
        
        club = await club_collection.find_one({"_id": club_object_id})
        
        if not club:
            return None
        
        if step_number == 1:
            return {
                "step_number": 1,
                "step_name": "Club Basic Information",
                "data": {
                    "name": club.get("name", ""),
                    "description": club.get("description", ""),
                    "sub_description": club.get("sub_description"),
                    "logo_url": club.get("logo_url"),
                    "banner_url": club.get("banner_url"),
                    "captain_details": club.get("captain_details", {})
                }
            }
        elif step_number == 2:
            return {
                "step_number": 2,
                "step_name": "What's Included + Top 3 Sports",
                "data": {
                    "whats_included": club.get("whats_included", []),
                    "top_3_sports": club.get("top_3_sports", [])
                }
            }
        elif step_number == 3:
            return {
                "step_number": 3,
                "step_name": "Pricing Setup",
                "data": {
                    "pricing_plans": club.get("pricing_plans", []),
                    "has_stripe_product": club.get("has_stripe_product", False),
                    "has_stripe_price": club.get("has_stripe_price", False),
                    "stripe_product_id": club.get("stripe_product_id"),
                    "total_plans": len(club.get("pricing_plans", []))
                }
            }
        elif step_number == 4:
            return {
                "step_number": 4,
                "step_name": "Moderator Setup",
                "data": {
                    "moderator_emails": club.get("moderator_emails", []),
                    "moderator_count": club.get("moderator_count", 0),
                    "free_moderators": club.get("free_moderators", 0),
                    "paid_moderators": club.get("paid_moderators", 0),
                    "additional_moderator_price": club.get("additional_moderator_price",9.95),
                    "additional_moderator_currency": club.get("additional_moderator_currency"),
                    "total_additional_moderator_pricing": club.get("total_additional_moderator_pricing", 0),
                    "stripe_product_id": club.get("stripe_product_id"),
                    "stripe_price_id": club.get("stripe_price_id"),
                    "moderator_invitations": club.get("moderator_invitations", [])
                }
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting club step details: {e}")
        return None

async def get_captain_progress_summary(captain_id: str) -> Optional[Dict[str, Any]]:
    """
    Get captain's club creation progress summary without detailed club information
    
    Returns a summary showing overall progress, completion status, and recent activity
    """
    try:
        club_collection = get_club_collection()
        user_collection = get_user_collection()
        
        # Verify captain exists
        captain_object_id = ObjectId(captain_id)
        captain = await user_collection.find_one({"_id": captain_object_id})
        
        if not captain:
            logger.warning(f"Captain not found: {captain_id}")
            return None
        
        # Get all clubs for this captain
        clubs = await club_collection.find({"captain_id": captain_id}).sort("created_at", -1).to_list(length=None)
        
        if not clubs:
            logger.info(f"No clubs found for captain: {captain_id}")
            return None
        
        # Prepare captain info
        captain_info = {
            "id": captain_id,
            "full_name": captain.get("full_name", ""),
            "name_based_id": captain.get("name_based_id", ""),
            "email": captain.get("email", ""),
            "total_clubs": len(clubs)
        }
        
        # Calculate step completion statistics
        step_stats = {
            "step_1_completed": len([c for c in clubs if c.get("club_complete_step", 0) >= 1]),
            "step_2_completed": len([c for c in clubs if c.get("club_complete_step", 0) >= 2]),
            "step_3_completed": len([c for c in clubs if c.get("club_complete_step", 0) >= 3]),
            "step_4_completed": len([c for c in clubs if c.get("club_complete_step", 0) >= 4])
        }
        
        # Calculate overall progress
        total_steps = 4
        total_possible_completions = len(clubs) * total_steps
        actual_completions = sum(min(c.get("club_complete_step", 0), total_steps) for c in clubs)
        overall_progress = {
            "total_steps": total_steps,
            "total_clubs": len(clubs),
            "total_possible_completions": total_possible_completions,
            "actual_completions": actual_completions,
            "completion_percentage": round((actual_completions / total_possible_completions) * 100, 2) if total_possible_completions > 0 else 0
        }
        
        # Get recent activity (last 3 clubs)
        recent_clubs = []
        for club in clubs[:3]:
            recent_clubs.append({
                "club_id": str(club["_id"]),
                "name": club.get("name", ""),
                "name_based_id": club.get("name_based_id", ""),
                "status": club.get("status", "pending"),
                "club_complete_step": club.get("club_complete_step", 0),
                "last_updated": club.get("updated_at"),
                "created_at": club.get("created_at")
            })
        
        # Prepare final response
        response_data = {
            "captain": captain_info,
            "overall_progress": overall_progress,
            "step_statistics": step_stats,
            "recent_activity": {
                "recent_clubs": recent_clubs,
                "last_activity": max([c.get("updated_at", c.get("created_at")) for c in clubs]) if clubs else None
            }
        }
        
        logger.info(f"Retrieved progress summary for captain {captain_id}: {len(clubs)} clubs, {actual_completions}/{total_possible_completions} steps completed")
        return response_data
        
    except Exception as e:
        logger.error(f"Error getting captain progress summary: {e}")
        return None
