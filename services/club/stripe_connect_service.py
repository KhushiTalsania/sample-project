"""
Stripe Connect Service

This service handles all Stripe Connect operations including:
- Captain onboarding
- Payment processing with revenue split
- Bank account management
- Payout processing
- Revenue tracking
"""

import os
import stripe
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from .db import get_club_collection, get_user_collection, get_membership_collection
from .models import PricingPlan
from .datetime_utils import safe_datetime_serialize, format_stripe_datetime

# Configure logging
logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
if not stripe.api_key:
    logger.warning("⚠️ STRIPE_SECRET_KEY not found in environment variables")

# Stripe Connect configuration
STRIPE_CONNECT_CLIENT_ID = os.getenv('STRIPE_CONNECT_CLIENT_ID')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
PLATFORM_FEE_PERCENTAGE = float(os.getenv('PLATFORM_FEE_PERCENTAGE', '5.0'))  # 5% platform fee
CAPTAIN_FEE_PERCENTAGE = 100.0 - PLATFORM_FEE_PERCENTAGE  # 95% captain fee

class StripeConnectService:
    """Service for handling Stripe Connect operations"""
    
    def __init__(self):
        self.club_collection = get_club_collection()
        self.user_collection = get_user_collection()
        self.membership_collection = get_membership_collection()
        
        # Create additional collections for revenue tracking
        self.revenue_collection = self.club_collection.database['revenue_tracking']
        self.payout_collection = self.club_collection.database['payout_tracking']
        self.captain_accounts_collection = self.club_collection.database['captain_stripe_accounts']
    
    # ==================== CAPTAIN ONBOARDING ====================
    
    async def create_captain_connect_account(self, captain_id: str, captain_email: str, 
                                           captain_name: str, country: str = 'US') -> Dict[str, Any]:
        """
        Create Stripe Connect account for captain
        
        Args:
            captain_id: Captain's user ID
            captain_email: Captain's email address
            captain_name: Captain's full name
            country: Country code (default: US)
            
        Returns:
            Dict with account details and onboarding URL
        """
        try:
            logger.info(f"🚀 Creating Stripe Connect account for captain: {captain_email}")
            
            # Check if captain already has a Connect account
            existing_account = await self.captain_accounts_collection.find_one({
                "captain_id": ObjectId(captain_id)
            })
            
            if existing_account:
                logger.info(f"Captain {captain_id} already has Connect account: {existing_account['account_id']}")
                return {
                    "success": True,
                    "account_id": existing_account["account_id"],
                    "status": existing_account["status"],
                    "message": "Captain already has a Stripe Connect account"
                }
            
            # Create Express account
            account = stripe.Account.create(
                type='express',
                country=country,
                email=captain_email,
                capabilities={
                    'card_payments': {'requested': True},
                    'transfers': {'requested': True},
                },
                business_type='individual',
                settings={
                    'payouts': {
                        'schedule': {
                            'interval': 'daily'  # Daily payouts
                        }
                    }
                }
            )
            
            logger.info(f"✅ Stripe Connect account created: {account.id}")
            
            # Create onboarding link
            account_link = stripe.AccountLink.create(
                account=account.id,
                refresh_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                return_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                type='account_onboarding',
            )
            
            # Store account details
            account_record = {
                "captain_id": ObjectId(captain_id),
                "account_id": account.id,
                "email": captain_email,
                "name": captain_name,
                "country": country,
                "status": "pending_onboarding",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await self.captain_accounts_collection.insert_one(account_record)
            
            # Update captain's user record with Stripe Connect details
            await self.user_collection.update_one(
                {"_id": ObjectId(captain_id)},
                {
                    "$set": {
                        "stripe_connect_account_id": account.id,
                        "stripe_connect_status": "pending_onboarding",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"✅ Captain Connect account setup completed for {captain_id}")
            
            return {
                "success": True,
                "account_id": account.id,
                "onboarding_url": account_link.url,
                "status": "pending_onboarding",
                "message": "Please complete Stripe onboarding to start receiving payments"
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error creating Connect account: {e}")
            return {"success": False, "error": f"Stripe error: {str(e)}"}
        except Exception as e:
            logger.error(f"❌ Error creating Connect account: {e}")
            return {"success": False, "error": f"Error creating Connect account: {str(e)}"}
    
    async def get_captain_account_status(self, captain_id: str) -> Dict[str, Any]:
        """
        Get captain's Stripe Connect account status
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            Dict with account status and details
        """
        try:
            # Get account record from database
            account_record = await self.captain_accounts_collection.find_one({
                "captain_id": ObjectId(captain_id)
            })
            
            if not account_record:
                return {
                    "success": False,
                    "error": "Captain has not created a Stripe Connect account"
                }
            
            # Get fresh account details from Stripe
            account = stripe.Account.retrieve(account_record["account_id"])
            
            # Update status in database
            status = "active" if account.details_submitted else "pending_onboarding"
            await self.captain_accounts_collection.update_one(
                {"captain_id": ObjectId(captain_id)},
                {"$set": {"status": status, "updated_at": datetime.utcnow()}}
            )
            
            return {
                "success": True,
                "account_id": account.id,
                "status": status,
                "details_submitted": account.details_submitted,
                "charges_enabled": account.charges_enabled,
                "payouts_enabled": account.payouts_enabled,
                "requirements": account.requirements,
                "created_at": safe_datetime_serialize(account_record["created_at"])
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error getting account status: {e}")
            return {"success": False, "error": f"Stripe error: {str(e)}"}
        except Exception as e:
            logger.error(f"❌ Error getting account status: {e}")
            return {"success": False, "error": f"Error getting account status: {str(e)}"}
    
    async def create_captain_login_link(self, captain_id: str) -> Dict[str, Any]:
        """
        Create login link for captain's Stripe dashboard
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            Dict with login URL
        """
        try:
            # Get captain's account ID
            account_record = await self.captain_accounts_collection.find_one({
                "captain_id": ObjectId(captain_id)
            })
            
            if not account_record:
                return {"success": False, "error": "Captain has not created a Stripe Connect account"}
            
            # Check if account has completed onboarding
            account = stripe.Account.retrieve(account_record["account_id"])
            
            if not account.details_submitted:
                # Create onboarding link instead of login link
                account_link = stripe.AccountLink.create(
                    account=account_record["account_id"],
                    refresh_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                    return_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin",
                    type='account_onboarding',
                )
                
                return {
                    "success": True,
                    "login_url": account_link.url,
                    "expires_at": account_link.expires_at,
                    "type": "onboarding",
                    "message": "Please complete Stripe onboarding to access your dashboard",
                    "requirements": account.requirements
                }
            
            # Create login link for completed accounts
            login_link = stripe.Account.create_login_link(
                account_record["account_id"],
                redirect_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin"
            )
            
            return {
                "success": True,
                "login_url": login_link.url,
                "expires_at": login_link.expires_at,
                "type": "dashboard",
                "message": "Access your Stripe dashboard"
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error creating login link: {e}")
            return {"success": False, "error": f"Stripe error: {str(e)}"}
        except Exception as e:
            logger.error(f"❌ Error creating login link: {e}")
            return {"success": False, "error": f"Error creating login link: {str(e)}"}
    
    async def get_dashboard_link_by_account_id(self, connected_account_id: str, 
                                               redirect_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a one-time login link for the connected account dashboard using account ID.
        This is useful for admin operations or when you have the account ID directly.
        
        Args:
            connected_account_id: Stripe Connect account ID (e.g., acct_xxxxx)
            redirect_url: Optional URL to redirect after login
            
        Returns:
            Dict with dashboard URL and details
        """
        try:
            # Verify account exists and get its details
            account = stripe.Account.retrieve(connected_account_id)
            
            if not account.details_submitted:
                # Account hasn't completed onboarding yet
                logger.warning(f"Account {connected_account_id} has not completed onboarding")
                
                # Generate onboarding link instead
                account_link = stripe.AccountLink.create(
                    account=connected_account_id,
                    refresh_url=redirect_url or f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/captain/stripe/reauth",
                    return_url=redirect_url or f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/captain/stripe/success",
                    type='account_onboarding',
                )
                
                return {
                    "success": True,
                    "dashboard_link": account_link.url,
                    "connected_account_id": connected_account_id,
                    "type": "onboarding",
                    "expires_at": account_link.expires_at,
                    "details_submitted": False,
                    "charges_enabled": account.charges_enabled,
                    "payouts_enabled": account.payouts_enabled,
                    "message": "Account onboarding not complete. Please complete onboarding first."
                }
            
            # Account is fully onboarded - generate dashboard login link
            login_link = stripe.Account.create_login_link(
                connected_account_id,
                redirect_url=redirect_url or f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/captain/dashboard"
            )
            
            logger.info(f"✅ Dashboard login link generated for account: {connected_account_id}")
            
            return {
                "success": True,
                "dashboard_link": login_link.url,
                "connected_account_id": connected_account_id,
                "type": "dashboard",
                "expires_at": login_link.created + 300,  # Links expire in 5 minutes
                "details_submitted": account.details_submitted,
                "charges_enabled": account.charges_enabled,
                "payouts_enabled": account.payouts_enabled,
                "message": "Dashboard link generated successfully. Link expires in 5 minutes."
            }
            
        except stripe.error.InvalidRequestError as e:
            logger.error(f"❌ Invalid account ID {connected_account_id}: {e}")
            return {
                "success": False, 
                "error": f"Invalid account ID or account not found: {str(e)}"
            }
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error generating dashboard link: {e}")
            return {
                "success": False, 
                "error": f"Stripe error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"❌ Error generating dashboard link: {e}")
            return {
                "success": False, 
                "error": f"Error generating dashboard link: {str(e)}"
            }
    
    # ==================== PAYMENT PROCESSING ====================
    
    async def process_payment_with_revenue_split(self, payment_method_id: str, amount: float,
                                               customer_id: str, club_id: str, captain_id: str,
                                               club_name: str, customer_name: str) -> Tuple[bool, Optional[str], Optional[str], str]:
        """
        Process payment with automatic revenue split
        
        Args:
            payment_method_id: Stripe payment method ID
            amount: Payment amount
            customer_id: Stripe customer ID
            club_id: Club ID
            captain_id: Captain's user ID
            club_name: Club name
            customer_name: Customer name
            
        Returns:
            Tuple of (success, payment_intent_id, subscription_id, error_message)
        """
        try:
            logger.info(f"💳 Processing payment with revenue split: ${amount}")
            
            # Get captain's Stripe Connect account
            captain_account = await self.captain_accounts_collection.find_one({
                "captain_id": ObjectId(captain_id)
            })
            
            if not captain_account:
                return False, None, None, "Captain has not set up Stripe Connect account"
            
            if captain_account["status"] != "active":
                return False, None, None, "Captain's Stripe Connect account is not active"
            
            # Calculate revenue split
            total_amount = int(amount * 100)  # Convert to cents
            application_fee = int(amount * PLATFORM_FEE_PERCENTAGE / 100 * 100)  # Platform fee in cents
            captain_amount = total_amount - application_fee  # Captain amount in cents
            
            logger.info(f"💰 Revenue split: Total=${amount}, Platform=${application_fee/100}, Captain=${captain_amount/100}")
            
            # Create payment intent with revenue split
            payment_intent = stripe.PaymentIntent.create(
                amount=total_amount,
                currency='usd',
                customer=customer_id,
                payment_method=payment_method_id,
                application_fee_amount=application_fee,  # Platform fee
                transfer_data={
                    'destination': captain_account["account_id"],  # Captain's account
                },
                confirm=True,
                payment_method_types=["card"],
                description=f"Paid membership for {club_name}",
                metadata={
                    'club_id': club_id,
                    'captain_id': captain_id,
                    'club_name': club_name,
                    'customer_name': customer_name,
                    'platform_fee': str(application_fee),
                    'captain_amount': str(captain_amount),
                    'payment_type': 'connect_payment'
                }
            )
            
            if payment_intent.status == 'succeeded':
                logger.info(f"✅ Payment succeeded: {payment_intent.id}")
                
                # Record revenue split
                await self._record_revenue_split(
                    club_id=club_id,
                    captain_id=captain_id,
                    total_amount=amount,
                    platform_fee=application_fee / 100,
                    captain_amount=captain_amount / 100,
                    payment_intent_id=payment_intent.id,
                    customer_id=customer_id
                )
                
                return True, payment_intent.id, f"connect_{payment_intent.id}", ""
            else:
                logger.error(f"❌ Payment failed with status: {payment_intent.status}")
                return False, None, None, f"Payment failed with status: {payment_intent.status}"
                
        except stripe.error.CardError as e:
            logger.error(f"💳❌ Card error: {e}")
            return False, None, None, f"Card error: {str(e)}"
        except stripe.error.StripeError as e:
            logger.error(f"💳❌ Stripe error: {e}")
            return False, None, None, f"Payment processing error: {str(e)}"
        except Exception as e:
            logger.error(f"💳❌ Unexpected error: {e}")
            return False, None, None, f"Payment processing error: {str(e)}"
    
    # ==================== REVENUE TRACKING ====================
    
    async def _record_revenue_split(self, club_id: str, captain_id: str, total_amount: float,
                                  platform_fee: float, captain_amount: float, payment_intent_id: str,
                                  customer_id: str) -> None:
        """Record revenue split for tracking and analytics"""
        try:
            revenue_record = {
                "club_id": ObjectId(club_id),
                "captain_id": ObjectId(captain_id),
                "customer_id": customer_id,
                "payment_intent_id": payment_intent_id,
                "total_amount": total_amount,
                "platform_fee": platform_fee,
                "captain_amount": captain_amount,
                "platform_percentage": PLATFORM_FEE_PERCENTAGE,
                "captain_percentage": CAPTAIN_FEE_PERCENTAGE,
                "status": "completed",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await self.revenue_collection.insert_one(revenue_record)
            logger.info(f"✅ Revenue split recorded: ${total_amount} split between platform and captain")
            
        except Exception as e:
            logger.error(f"❌ Error recording revenue split: {e}")
    
    # ==================== CAPTAIN DASHBOARD ====================
    
    async def get_captain_dashboard_data(self, captain_id: str) -> Dict[str, Any]:
        """
        Get comprehensive dashboard data for captain
        
        Args:
            captain_id: Captain's user ID
            
        Returns:
            Dict with dashboard data
        """
        try:
            # Get captain's account
            captain_account = await self.captain_accounts_collection.find_one({
                "captain_id": ObjectId(captain_id)
            })
            
            if not captain_account:
                return {"success": False, "error": "Captain has not set up Stripe Connect account"}
            
            # Get Stripe account details
            account = stripe.Account.retrieve(captain_account["account_id"])
            
            # Get balance
            balance = stripe.Balance.retrieve(stripe_account=captain_account["account_id"])
            
            # Get recent payouts
            payouts = stripe.Payout.list(
                stripe_account=captain_account["account_id"],
                limit=10
            )
            
            # Get recent charges
            charges = stripe.Charge.list(
                stripe_account=captain_account["account_id"],
                limit=10
            )
            
            # Get revenue data from our database
            revenue_data = await self._get_captain_revenue_data(captain_id)
            
            return {
                "success": True,
                "account": {
                    "id": account.id,
                    "email": account.email,
                    "country": account.country,
                    "business_type": account.business_type,
                    "details_submitted": account.details_submitted,
                    "charges_enabled": account.charges_enabled,
                    "payouts_enabled": account.payouts_enabled
                },
                "balance": {
                    "available": balance.available[0].amount / 100,
                    "pending": balance.pending[0].amount / 100,
                    "currency": balance.available[0].currency
                },
                "payouts": [
                    {
                        "id": payout.id,
                        "amount": payout.amount / 100,
                        "status": payout.status,
                        "arrival_date": format_stripe_datetime(payout.arrival_date),
                        "created": format_stripe_datetime(payout.created),
                        "method": payout.method
                    } for payout in payouts.data
                ],
                "transactions": [
                    {
                        "id": charge.id,
                        "amount": charge.amount / 100,
                        "status": charge.status,
                        "created": format_stripe_datetime(charge.created),
                        "description": charge.description,
                        "currency": charge.currency
                    } for charge in charges.data
                ],
                "revenue_summary": revenue_data
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error getting dashboard data: {e}")
            return {"success": False, "error": f"Stripe error: {str(e)}"}
        except Exception as e:
            logger.error(f"❌ Error getting dashboard data: {e}")
            return {"success": False, "error": f"Error getting dashboard data: {str(e)}"}
    
    async def _get_captain_revenue_data(self, captain_id: str) -> Dict[str, Any]:
        """Get captain's revenue data from our database"""
        try:
            # Get total revenue
            total_revenue = await self.revenue_collection.aggregate([
                {"$match": {"captain_id": ObjectId(captain_id), "status": "completed"}},
                {"$group": {
                    "_id": None,
                    "total_earnings": {"$sum": "$captain_amount"},
                    "total_transactions": {"$sum": 1},
                    "platform_fees": {"$sum": "$platform_fee"}
                }}
            ]).to_list(None)
            
            # Get monthly revenue
            monthly_revenue = await self.revenue_collection.aggregate([
                {"$match": {"captain_id": ObjectId(captain_id), "status": "completed"}},
                {"$group": {
                    "_id": {
                        "year": {"$year": "$created_at"},
                        "month": {"$month": "$created_at"}
                    },
                    "monthly_earnings": {"$sum": "$captain_amount"},
                    "monthly_transactions": {"$sum": 1}
                }},
                {"$sort": {"_id.year": -1, "_id.month": -1}},
                {"$limit": 12}
            ]).to_list(None)
            
            return {
                "total_earnings": total_revenue[0]["total_earnings"] if total_revenue else 0,
                "total_transactions": total_revenue[0]["total_transactions"] if total_revenue else 0,
                "platform_fees": total_revenue[0]["platform_fees"] if total_revenue else 0,
                "monthly_breakdown": monthly_revenue
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting revenue data: {e}")
            return {
                "total_earnings": 0,
                "total_transactions": 0,
                "platform_fees": 0,
                "monthly_breakdown": []
            }
    
    # ==================== BANK ACCOUNT MANAGEMENT ====================
    
    async def add_bank_account(self, captain_id: str, bank_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add bank account to captain's Stripe Connect account
        
        Args:
            captain_id: Captain's user ID
            bank_details: Bank account details
            
        Returns:
            Dict with success status
        """
        try:
            # Get captain's account
            captain_account = await self.captain_accounts_collection.find_one({
                "captain_id": ObjectId(captain_id)
            })
            print(captain_account,"captain_account")
            if not captain_account:
                return {"success": False, "error": "Captain has not set up Stripe Connect account"}
            
            # Check if captain's account is properly set up
            account = stripe.Account.retrieve(captain_account["account_id"])
            
            if not account.details_submitted:
                return {
                    "success": False, 
                    "error": "Captain must complete Stripe onboarding before adding bank accounts. Please complete the onboarding process first."
                }
            
            # For Express accounts, we need to use a different approach
            # Instead of directly adding bank accounts, we'll store the details
            # and let the captain add them through their Stripe dashboard
            
            # Store bank account details for captain to add manually
            bank_account_record = {
                "captain_id": ObjectId(captain_id),
                "account_holder_name": bank_details['account_holder_name'],
                "account_number": bank_details['account_number'],
                "routing_number": bank_details['routing_number'],
                "bank_name": bank_details['bank_name'],
                "account_holder_type": bank_details.get('account_holder_type', 'individual'),
                "country": bank_details.get('country', 'US'),
                "currency": bank_details.get('currency', 'usd'),
                "status": "pending_manual_add",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # Store in database
            await self.club_collection.database['captain_bank_details'].insert_one(bank_account_record)
            
            # Create login link for captain to add bank account manually
            login_link = stripe.Account.create_login_link(
                captain_account["account_id"],
                redirect_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin"
            )
            
            logger.info(f"✅ Bank account details stored for captain {captain_id}")
            
            return {
                "success": True,
                "message": "Bank account details stored. Please complete the process in your Stripe dashboard.",
                "dashboard_url": login_link.url,
                "instructions": "Click the dashboard link to add your bank account manually in Stripe"
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error adding bank account: {e}")
            return {"success": False, "error": f"Stripe error: {str(e)}"}
        except Exception as e:
            logger.error(f"❌ Error adding bank account: {e}")
            return {"success": False, "error": f"Error adding bank account: {str(e)}"}
    
    async def get_bank_accounts(self, captain_id: str) -> Dict[str, Any]:
        """Get captain's bank accounts"""
        try:
            # Get captain's account
            captain_account = await self.captain_accounts_collection.find_one({
                "captain_id": ObjectId(captain_id)
            })
            
            if not captain_account:
                return {"success": False, "error": "Captain has not set up Stripe Connect account"}
            
            # Check if captain's account is properly set up
            account = stripe.Account.retrieve(captain_account["account_id"])
            
            if not account.details_submitted:
                return {
                    "success": False, 
                    "error": "Captain must complete Stripe onboarding before viewing bank accounts. Please complete the onboarding process first."
                }
            
            # Get stored bank account details from our database
            stored_bank_details = await self.club_collection.database['captain_bank_details'].find({
                "captain_id": ObjectId(captain_id)
            }).to_list(None)
            
            # Try to get bank accounts from Stripe (if permissions allow)
            stripe_bank_accounts = []
            try:
                external_accounts = stripe.Account.list_external_accounts(
                    captain_account["account_id"],
                    object="bank_account"
                )
                
                for account in external_accounts.data:
                    stripe_bank_accounts.append({
                        "id": account.id,
                        "bank_name": account.bank_name,
                        "last4": account.last4,
                        "routing_number": account.routing_number,
                        "account_holder_name": account.account_holder_name,
                        "account_holder_type": account.account_holder_type,
                        "currency": account.currency,
                        "default_for_currency": account.default_for_currency,
                        "source": "stripe"
                    })
            except stripe.error.StripeError as e:
                logger.warning(f"Could not fetch bank accounts from Stripe: {e}")
                # Continue with stored details only
            
            # Format stored bank details
            stored_bank_accounts = []
            for detail in stored_bank_details:
                stored_bank_accounts.append({
                    "id": str(detail["_id"]),
                    "bank_name": detail["bank_name"],
                    "account_number": detail["account_number"][-4:],  # Show only last 4 digits
                    "routing_number": detail["routing_number"],
                    "account_holder_name": detail["account_holder_name"],
                    "account_holder_type": detail["account_holder_type"],
                    "currency": detail["currency"],
                    "status": detail["status"],
                    "source": "stored"
                })
            
            # Create login link for captain to manage bank accounts
            login_link = stripe.Account.create_login_link(
                captain_account["account_id"],
                redirect_url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/signin"
            )
            
            return {
                "success": True,
                "stripe_bank_accounts": stripe_bank_accounts,
                "stored_bank_accounts": stored_bank_accounts,
                "dashboard_url": login_link.url,
                "message": "Use the dashboard link to manage bank accounts in Stripe"
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error getting bank accounts: {e}")
            return {"success": False, "error": f"Stripe error: {str(e)}"}
        except Exception as e:
            logger.error(f"❌ Error getting bank accounts: {e}")
            return {"success": False, "error": f"Error getting bank accounts: {str(e)}"}
    
    # ==================== PAYOUT MANAGEMENT ====================
    
    async def update_payout_settings(self, captain_id: str, payout_schedule: Dict[str, Any]) -> Dict[str, Any]:
        """Update captain's payout settings"""
        try:
            # Get captain's account
            captain_account = await self.captain_accounts_collection.find_one({
                "captain_id": ObjectId(captain_id)
            })
            
            if not captain_account:
                return {"success": False, "error": "Captain has not set up Stripe Connect account"}
            
            # Update payout settings
            account = stripe.Account.modify(
                captain_account["account_id"],
                settings={
                    'payouts': {
                        'schedule': {
                            'interval': payout_schedule.get('interval', 'daily'),
                            'weekly_anchor': payout_schedule.get('weekly_anchor', 'friday')
                        }
                    }
                }
            )
            
            logger.info(f"✅ Payout settings updated for captain {captain_id}")
            
            return {
                "success": True,
                "message": "Payout settings updated successfully"
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error updating payout settings: {e}")
            return {"success": False, "error": f"Stripe error: {str(e)}"}
        except Exception as e:
            logger.error(f"❌ Error updating payout settings: {e}")
            return {"success": False, "error": f"Error updating payout settings: {str(e)}"}
    
    async def get_payout_history(self, captain_id: str, limit: int = 20) -> Dict[str, Any]:
        """Get captain's payout history"""
        try:
            # Get captain's account
            captain_account = await self.captain_accounts_collection.find_one({
                "captain_id": ObjectId(captain_id)
            })
            
            if not captain_account:
                return {"success": False, "error": "Captain has not set up Stripe Connect account"}
            
            # Get payouts
            payouts = stripe.Payout.list(
                stripe_account=captain_account["account_id"],
                limit=limit
            )
            
            payout_list = []
            for payout in payouts.data:
                payout_list.append({
                    "id": payout.id,
                    "amount": payout.amount / 100,
                    "currency": payout.currency,
                    "status": payout.status,
                    "arrival_date": format_stripe_datetime(payout.arrival_date),
                    "created": format_stripe_datetime(payout.created),
                    "method": payout.method,
                    "description": payout.description
                })
            
            return {
                "success": True,
                "payouts": payout_list,
                "has_more": payouts.has_more
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"❌ Stripe error getting payout history: {e}")
            return {"success": False, "error": f"Stripe error: {str(e)}"}
        except Exception as e:
            logger.error(f"❌ Error getting payout history: {e}")
            return {"success": False, "error": f"Error getting payout history: {str(e)}"}

# Global instance
stripe_connect_service = StripeConnectService()

def get_stripe_connect_service():
    """Get Stripe Connect service instance"""
    return stripe_connect_service
