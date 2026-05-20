import stripe
import os
from typing import List, Dict, Optional
from datetime import datetime
from .models import PricingPlan
from .db import get_club_collection
from bson import ObjectId
import asyncio
# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')

# Test Stripe connection
try:
    print(f"🔑 Stripe API Key: {stripe.api_key[:20]}...")
    print(f"🌍 Stripe Environment: {'test' if 'test' in stripe.api_key else 'live'}")
except Exception as e:
    print(f"❌ Error initializing Stripe: {e}")

class StripeService:
    """Service for handling Stripe operations for club pricing plans"""
    
    @staticmethod
    async def test_stripe_connection() -> bool:
        """Test if Stripe API is working"""
        try:
            print("🧪 Testing Stripe API connection...")
            account = stripe.Account.retrieve()
            print(f"✅ Stripe connection successful! Account ID: {account.id}")
            return True
        except Exception as e:
            print(f"❌ Stripe connection failed: {e}")
            return False
    
    @staticmethod
    async def create_product_for_club(club_id: str, club_name: str, captain_id: str, admin_id: str = None) -> str:
        """Create a Stripe product for a club"""
        try:
            print(f"🏭 Creating Stripe product for club: {club_name}")
            print(f"📝 Product details: name='{club_name} - Club Membership', club_id={club_id}")
            
            # TODO: For better duplicate detection, consider:
            # 1. Store product IDs in your database
            # 2. Use Stripe's search API (if available in your version)
            # 3. Implement a custom duplicate detection strategy
            
            # Prepare metadata
            metadata = {
                "club_id": club_id,
                "captain_id": captain_id,
                "type": "club_membership"
            }
            print("admin_idadmin_idadmin_id",admin_id)
            # Add admin_id to metadata if provided
            if admin_id:
                metadata["admin_id"] = admin_id
                print(f"📝 Including admin_id in product metadata: {admin_id}")
            
            # Create new product
            product = stripe.Product.create(
                name=f"{club_name} - Club Membership",
                description=f"Membership for {club_name} club",
                metadata=metadata
            )
            print(f"✅ Created new Stripe product: {product.id} for club: {club_name}")
            print(f"🔍 Product metadata: {product.metadata}")
            return product.id
        except Exception as e:
            print(f"❌ Error creating Stripe product: {str(e)}")
            raise Exception(f"Failed to create Stripe product: {str(e)}")
    
    @staticmethod
    async def create_price_for_plan(
        product_id: str, 
        pricing_plan: dict,
        club_id: str,
        captain_id: str,
        admin_id: str = None
    ) -> str:
        """Create a Stripe price for a specific pricing plan"""
        try:
            print(f"💰 Creating Stripe price for plan: {pricing_plan}")
            
            # Determine interval based on plan frequency
            plan_frequency = pricing_plan.get("frequency", "monthly")
            print(f"📅 Plan frequency: {plan_frequency}")
            
            if plan_frequency == "daily":
                recurring_config = {"interval": "day"}
            elif plan_frequency == "weekly":
                recurring_config = {"interval": "week"}
            elif plan_frequency == "monthly":
                recurring_config = {"interval": "month"}
            elif plan_frequency == "quarterly":
                recurring_config = {"interval": "month", "interval_count": 3}
            elif plan_frequency == "yearly":
                recurring_config = {"interval": "year"}
            elif plan_frequency == "lifetime":
                # For lifetime, we'll create a one-time payment (no recurring)
                recurring_config = None
            else:
                raise Exception(f"Invalid plan frequency: {plan_frequency}")
            
            print(f"🔄 Recurring config: {recurring_config}")
            
            # Prepare metadata
            price_metadata = {
                "club_id": club_id,
                "captain_id": captain_id,
                "pricing_plan": plan_frequency,
                "type": "club_membership"
            }
            
            # Add admin_id to metadata if provided
            if admin_id:
                price_metadata["admin_id"] = admin_id
                print(f"📝 Including admin_id in price metadata: {admin_id}")
            
            # Create new price
            price_params = {
                "product": product_id,
                "unit_amount": int(pricing_plan.get("price", 0) * 100),  # Convert to cents
                "currency": pricing_plan.get("currency", "USD").lower(),
                "metadata": price_metadata
            }
            
            # Add recurring config only if not lifetime
            if recurring_config is not None:
                price_params["recurring"] = recurring_config
            
            print(f"📝 Price params: {price_params}")
            
            price = stripe.Price.create(**price_params)
            print(f"✅ Created new Stripe price: {price.id} for {plan_frequency} plan")
            print(f"🔍 Price metadata: {price.metadata}")
            return price.id
        except Exception as e:
            print(f"❌ Error creating Stripe price: {str(e)}")
            raise Exception(f"Failed to create Stripe price: {str(e)}")
    
    @staticmethod
    async def create_pricing_plans_for_club(
        club_id: str, 
        club_name: str,
        captain_id: str,
        pricing_plans: List[dict],
        admin_id: str = None
    ) -> List[dict]:
        """Create all pricing plans for a club in Stripe"""
        try:
            print(f"🔄 Starting Stripe pricing plan creation for club: {club_id}")
            print(f"📋 Plans to create: {pricing_plans}")
            
            # Create product first
            print(f"🏭 Creating Stripe product for club: {club_name}")
            product_id = await StripeService.create_product_for_club(club_id, club_name, captain_id, admin_id)
            print(f"✅ Stripe product created: {product_id}")
            
            updated_plans = []
            for i, plan in enumerate(pricing_plans):
                print(f"💰 Creating price for plan {i+1}: {plan}")
                # Create price for this plan
                price_id = await StripeService.create_price_for_plan(
                    product_id, plan, club_id, captain_id, admin_id
                )
                print(f"✅ Price created: {price_id}")
                
                # Update plan with Stripe IDs
                updated_plan = {
                    **plan,
                    "stripe_product_id": product_id,
                    "stripe_price_id": price_id,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
                updated_plans.append(updated_plan)
                print(f"📝 Updated plan {i+1}: {updated_plan}")
            
            print(f"🎉 All {len(updated_plans)} pricing plans created successfully!")
            return updated_plans
        except Exception as e:
            print(f"❌ Error creating pricing plans for club: {str(e)}")
            raise Exception(f"Failed to create pricing plans: {str(e)}")
    
    @staticmethod
    async def create_subscription(
        customer_id: str,
        price_id: str,
        payment_method_id: str,
        metadata: Dict
    ) -> stripe.Subscription:
        """Create a subscription for club membership"""
        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                  application_fee_percent=5,
                    transfer_data={
                        'destination': provider_account_id,
                    },
                default_payment_method=payment_method_id,
                expand=['latest_invoice.payment_intent'],
                metadata=metadata
            )
            print(f"✅ Created subscription: {subscription.id}")
            return subscription
        except Exception as e:
            print(f"❌ Error creating subscription: {str(e)}")
            raise Exception(f"Failed to create subscription: {str(e)}")
    
    @staticmethod
    async def get_or_create_stripe_customer(user_id: str, email: str, name: str) -> str:
        """Get existing or create new Stripe customer"""
        try:
            # Try to find existing customer by metadata
            customers = stripe.Customer.list(
                email=email,
                limit=1
            )
            
            if customers.data:
                customer = customers.data[0]
                print(f"✅ Found existing Stripe customer: {customer.id}")
                return customer.id
            
            # Create new customer
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata={
                    "user_id": user_id,
                    "type": "club_member"
                }
            )
            print(f"✅ Created new Stripe customer: {customer.id}")
            return customer.id
        except Exception as e:
            print(f"❌ Error with Stripe customer: {str(e)}")
            raise Exception(f"Failed to handle Stripe customer: {str(e)}")
    
    @staticmethod
    async def update_club_pricing_plans(club_id: str, pricing_plans: List[dict]):
        """Update club's pricing plans in database"""
        try:
            club_collection = get_club_collection()
            
            # Plans are already in dict format, no conversion needed
            plans_data = pricing_plans
            
            # Try to update by ObjectId first
            try:
                club_object_id = ObjectId(club_id)
                result = await club_collection.update_one(
                    {"_id": club_object_id},
                    {
                        "$set": {
                            "pricing_plans": plans_data,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                if result.modified_count > 0:
                    print(f"✅ Updated pricing plans for club ObjectId: {club_id}")
                    return
            except Exception:
                pass
            
            # If ObjectId update failed, try to find by name_based_id
            club = await club_collection.find_one({"name_based_id": club_id})
            if club:
                await club_collection.update_one(
                    {"name_based_id": club_id},
                    {
                        "$set": {
                            "pricing_plans": plans_data,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                print(f"✅ Updated pricing plans for club name_based_id: {club_id}")
            else:
                raise Exception(f"Club not found with ID: {club_id}")
                
        except Exception as e:
            print(f"❌ Error updating club pricing plans: {str(e)}")
            raise Exception(f"Failed to update club pricing plans: {str(e)}")
    
    @staticmethod
    async def validate_price_id(price_id: str, club_id: str) -> bool:
        """Validate that a price_id belongs to the specified club"""
        try:
            price = stripe.Price.retrieve(price_id)
            return price.metadata.get("club_id") == club_id
        except Exception as e:
            print(f"❌ Error validating price_id: {str(e)}")
            return False
    
    @staticmethod
    def handle_subscription_webhook(event_data: Dict) -> Dict:
        """Handle subscription-related webhook events"""
        event_type = event_data.get('type')
        data = event_data.get('data', {}).get('object', {})
        
        result = {
            "event_type": event_type,
            "subscription_id": data.get('id'),
            "customer_id": data.get('customer'),
            "status": data.get('status'),
            "metadata": data.get('metadata', {}),
            "amount": None,
            "currency": None
        }
        
        # Handle different event types
        if event_type in ['invoice.payment_succeeded', 'invoice.payment_failed']:
            result["amount"] = data.get('amount_paid', 0) / 100 if data.get('amount_paid') else 0
            result["currency"] = data.get('currency')
            result["invoice_id"] = data.get('id')
        
        return result 
    
    @staticmethod
    async def create_test_payment_method(customer_email: str = None) -> dict:
        """Create a test payment method for testing purposes"""
        try:
            print(f"🧪 Creating test payment method for customer: {customer_email}")
            
            # Create a test payment method using Stripe's test card
            payment_method = stripe.PaymentMethod.create(
                type="card",
                card={
                    "number": "4242424242424242",  # Test card number
                    "exp_month": 12,
                    "exp_year": 2025,
                    "cvc": "123"
                }
            )
            
            print(f"✅ Test payment method created: {payment_method.id}")
            
            # If customer email is provided, create a customer and attach the payment method
            if customer_email:
                try:
                    customer = stripe.Customer.create(
                        email=customer_email,
                        payment_method=payment_method.id,
                        invoice_settings={"default_payment_method": payment_method.id}
                    )
                    print(f"✅ Test customer created: {customer.id}")
                    payment_method.customer = customer.id
                except Exception as e:
                    print(f"⚠️ Could not create customer: {e}")
            
            return payment_method
            
        except Exception as e:
            print(f"❌ Failed to create test payment method: {e}")
            raise Exception(f"Failed to create test payment method: {str(e)}")
    
    @staticmethod
    async def create_payment_intent_from_card(
        amount: int,
        currency: str = "usd",
        card_number: str = "4242424242424242",
        exp_month: int = 12,
        exp_year: int = 2025,
        cvc: str = "123",
        customer_email: str = None,
        metadata: dict = None,
        confirm: bool = False
    ) -> dict:
        """Create a Stripe payment intent directly from card details (for testing)"""
        try:
            print(f"💳 Creating payment intent from card for ${amount/100:.2f} {currency.upper()}")
            
            # Create payment intent data
            payment_intent_data = {
                "amount": amount,
                "currency": currency,
                "automatic_payment_methods": {"enabled": True},
                "payment_method_data": {
                    "type": "card",
                    "card": {
                        "number": card_number,
                        "exp_month": exp_month,
                        "exp_year": exp_year,
                        "cvc": cvc
                    }
                }
            }
            
            if customer_email:
                payment_intent_data["receipt_email"] = customer_email
            
            if metadata:
                payment_intent_data["metadata"] = metadata
            
            if confirm:
                payment_intent_data["confirm"] = True
            
            print(f"📝 Payment intent data: {payment_intent_data}")
            
            payment_intent = stripe.PaymentIntent.create(**payment_intent_data)
            
            print(f"✅ Payment intent created: {payment_intent.id}, status: {payment_intent.status}")
            return payment_intent
            
        except stripe.error.CardError as e:
            print(f"❌ Card error: {e}")
            raise Exception(f"Card error: {e.user_message or str(e)}")
        except stripe.error.InvalidRequestError as e:
            print(f"❌ Invalid request error: {e}")
            raise Exception(f"Invalid request: {str(e)}")
        except stripe.error.AuthenticationError as e:
            print(f"❌ Authentication error: {e}")
            raise Exception(f"Authentication failed: {str(e)}")
        except stripe.error.APIConnectionError as e:
            print(f"❌ API connection error: {e}")
            raise Exception(f"Network error: {str(e)}")
        except stripe.error.StripeError as e:
            print(f"❌ Stripe error: {e}")
            raise Exception(f"Stripe error: {str(e)}")
        except Exception as e:
            print(f"❌ Failed to create payment intent: {e}")
            raise Exception(f"Failed to create payment intent: {str(e)}")
    
    @staticmethod
    async def confirm_payment_intent(payment_intent_id: str, payment_method: str = None, customer_id: str = None) -> dict:
        """Confirm a payment intent"""
        try:
            print(f"💳 Confirming payment intent: {payment_intent_id}")
            
            confirm_data = {}
            if payment_method:
                confirm_data["payment_method"] = payment_method
            if customer_id:
                confirm_data["customer"] = customer_id
                print(f"👤 Including customer ID in confirmation: {customer_id}")
            
            confirmed_intent = stripe.PaymentIntent.confirm(
                payment_intent_id,
                **confirm_data
            )
            
            print(f"✅ Payment intent confirmed: {payment_intent_id}, status: {confirmed_intent.status}")
            return confirmed_intent
            
        except Exception as e:
            print(f"❌ Failed to confirm payment intent: {e}")
            raise Exception(f"Failed to confirm payment intent: {str(e)}")
    
    @staticmethod
    async def create_payment_intent(
        amount: int, 
        currency: str = "usd", 
        payment_method_id: str = None,
        customer_email: str = None,
        metadata: dict = None,
        confirm: bool = False,
        return_url: str = None
    ) -> dict:
        """Create a Stripe payment intent for one-time payments"""
        try:
            print(f"💳 Creating payment intent for ${amount/100:.2f} {currency.upper()}")
            
            customer_id = None
            
            # Validate payment method if provided
            if payment_method_id:
                try:
                    payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
                    print(f"✅ Payment method validated: {payment_method.id}, type: {payment_method.type}")
                    
                    # Check if payment method is attached to a customer
                    if payment_method.customer:
                        customer_id = payment_method.customer
                        print(f"✅ Payment method {payment_method_id} is attached to customer: {customer_id}")
                    else:
                        print(f"⚠️ Payment method {payment_method_id} is not attached to a customer")
                        # Try to create a customer and attach the payment method
                        if customer_email:
                            try:
                                customer = stripe.Customer.create(
                                    email=customer_email,
                                    payment_method=payment_method_id,
                                    invoice_settings={"default_payment_method": payment_method_id}
                                )
                                customer_id = customer.id
                                print(f"✅ Created customer {customer_id} and attached payment method")
                            except Exception as customer_error:
                                print(f"❌ Failed to create customer: {customer_error}")
                                raise Exception(f"Payment method {payment_method_id} is not attached to a customer and we couldn't create one: {str(customer_error)}")
                        else:
                            raise Exception(f"Payment method {payment_method_id} is not attached to a customer. Please provide customer_email to create one.")
                    
                except stripe.error.InvalidRequestError as e:
                    if "No such PaymentMethod" in str(e):
                        raise Exception(f"Payment method {payment_method_id} does not exist. Please check the payment method ID or create a new one.")
                    else:
                        raise e
                except Exception as e:
                    print(f"❌ Error validating payment method: {e}")
                    raise Exception(f"Failed to validate payment method {payment_method_id}: {str(e)}")
            
            payment_intent_data = {
                "amount": amount,
                "currency": currency,
                "automatic_payment_methods": {
                    "enabled": True,
                    "allow_redirects": "never"  # Prevent redirect-based payment methods
                }
            }
            
            # Include customer ID if we have one
            if customer_id:
                payment_intent_data["customer"] = customer_id
                print(f"👤 Including customer ID: {customer_id}")
            
            if payment_method_id:
                payment_intent_data["payment_method"] = payment_method_id
            
            if customer_email and not customer_id:
                payment_intent_data["receipt_email"] = customer_email
            
            if metadata:
                payment_intent_data["metadata"] = metadata
            
            # Only set confirm=True if explicitly requested and we have a return_url
            if confirm and return_url:
                payment_intent_data["confirm"] = True
                payment_intent_data["return_url"] = return_url
                # Allow redirects if return_url is provided
                payment_intent_data["automatic_payment_methods"]["allow_redirects"] = "always"
            elif confirm and not return_url:
                # If confirm is requested but no return_url, create without confirmation
                print("⚠️ Confirm=True requested but no return_url provided. Creating unconfirmed payment intent.")
                payment_intent_data["confirm"] = False
            
            print(f"📝 Payment intent data: {payment_intent_data}")
            
            payment_intent = stripe.PaymentIntent.create(**payment_intent_data)
            
            print(f"✅ Payment intent created: {payment_intent.id}, status: {payment_intent.status}")
            return payment_intent
            
        except stripe.error.CardError as e:
            print(f"❌ Card error: {e}")
            raise Exception(f"Card error: {e.user_message or str(e)}")
        except stripe.error.InvalidRequestError as e:
            print(f"❌ Invalid request error: {e}")
            raise Exception(f"Invalid request: {str(e)}")
        except stripe.error.AuthenticationError as e:
            print(f"❌ Authentication error: {e}")
            raise Exception(f"Authentication failed: {str(e)}")
        except stripe.error.APIConnectionError as e:
            print(f"❌ API connection error: {e}")
            raise Exception(f"Network error: {str(e)}")
        except stripe.error.StripeError as e:
            print(f"❌ Stripe error: {e}")
            raise Exception(f"Stripe error: {str(e)}")
        except Exception as e:
            print(f"❌ Failed to create payment intent: {e}")
            raise Exception(f"Failed to create payment intent: {str(e)}")