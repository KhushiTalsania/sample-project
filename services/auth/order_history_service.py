"""
Order History Service

This service handles retrieving order history for members,
including platform fees from payments table and club memberships
from club_memberships table.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from bson import ObjectId
import stripe
from core.database.collections import get_collections
from core.utils.response_utils import create_response

logger = logging.getLogger(__name__)

# def _get_stripe_receipt_urls(payment_id: str) -> Optional[str]:
#     """Get receipt URL from Stripe for a payment ID"""
#     try:
#         logger.info(f"🔍 Attempting to get receipt URL for payment_id: {payment_id}")
        
#         if not payment_id:
#             logger.info("❌ No payment_id provided")
#             return None
        
#         # Handle different payment ID types
#         if payment_id.startswith('pi_'):  # Payment Intent
#             logger.info(f"📋 Processing Payment Intent: {payment_id}")
#             try:
#                 # Get payment intent and find the latest charge - expand charges to get full data
#                 payment_intent = stripe.PaymentIntent.retrieve(payment_id, expand=['charges'])
#                 logger.info(f"✅ Retrieved Payment Intent: {payment_intent.id}, status: {payment_intent.status}")
                
#                 if payment_intent and payment_intent.charges:
#                     logger.info(f"🔍 Found {len(payment_intent.charges.data)} charges")
#                     # Get the latest charge
#                     charges = payment_intent.charges.data
#                     if charges:
#                         latest_charge = charges[-1]  # Most recent charge
#                         logger.info(f"🔍 Latest charge: {latest_charge.id}, status: {latest_charge.status}")
                        
#                         if latest_charge.receipt_url:
#                             logger.info(f"✅ Found receipt URL: {latest_charge.receipt_url}")
#                             return latest_charge.receipt_url
#                         else:
#                             logger.info(f"❌ No receipt_url on charge: {latest_charge.id}")
                            
#                             # Try to get invoice PDF
#                             if hasattr(latest_charge, 'invoice') and latest_charge.invoice:
#                                 logger.info(f"🔍 Trying to get invoice: {latest_charge.invoice}")
#                                 try:
#                                     invoice = stripe.Invoice.retrieve(latest_charge.invoice)
#                                     if invoice and invoice.invoice_pdf:
#                                         logger.info(f"✅ Found invoice PDF: {invoice.invoice_pdf}")
#                                         return invoice.invoice_pdf
#                                     else:
#                                         logger.info(f"❌ No invoice_pdf on invoice: {invoice.id}")
#                                 except Exception as invoice_e:
#                                     logger.error(f"❌ Error retrieving invoice: {invoice_e}")
#                             else:
#                                 logger.info(f"❌ No invoice on charge: {latest_charge.id}")
#                     else:
#                         logger.info(f"❌ No charges found in payment intent")
#                 else:
#                     logger.info(f"❌ No charges found in payment intent")
                    
#                     # Alternative: Try to list charges for this payment intent
#                     try:
#                         logger.info(f"🔍 Trying to list charges for payment intent: {payment_id}")
#                         charges_list = stripe.Charge.list(payment_intent=payment_id, limit=1)
#                         if charges_list.data:
#                             charge = charges_list.data[0]
#                             logger.info(f"🔍 Found charge via list: {charge.id}, status: {charge.status}")
#                             if charge.receipt_url:
#                                 logger.info(f"✅ Found receipt URL via list: {charge.receipt_url}")
#                                 return charge.receipt_url
#                             else:
#                                 logger.info(f"❌ No receipt_url on charge via list: {charge.id}")
#                         else:
#                             logger.info(f"❌ No charges found via list for payment intent")
#                     except Exception as list_e:
#                         logger.error(f"❌ Error listing charges: {list_e}")
                        
#                         # Final fallback: Try to create a receipt URL manually
#                         try:
#                             logger.info(f"🔧 Attempting to create receipt URL manually...")
#                             # For some payment intents, we can construct a receipt URL
#                             if payment_intent.status == 'succeeded':
#                                 # Try to get the charge ID and create receipt URL
#                                 if payment_intent.latest_charge:
#                                     charge_id = payment_intent.latest_charge
#                                     logger.info(f"🔍 Found latest charge ID: {charge_id}")
#                                     # Construct receipt URL manually
#                                     receipt_url = f"https://dashboard.stripe.com/payments/{charge_id}"
#                                     logger.info(f"🔧 Generated receipt URL: {receipt_url}")
#                                     return receipt_url
#                         except Exception as fallback_e:
#                             logger.error(f"❌ Error in fallback receipt generation: {fallback_e}")
                            
#             except Exception as pi_e:
#                 logger.error(f"❌ Error retrieving payment intent {payment_id}: {pi_e}")
        
#         elif payment_id.startswith('ch_'):  # Direct Charge ID
#             logger.info(f"📋 Processing Direct Charge: {payment_id}")
#             try:
#                 charge = stripe.Charge.retrieve(payment_id)
#                 logger.info(f"✅ Retrieved Charge: {charge.id}, status: {charge.status}")
#                 if charge and charge.receipt_url:
#                     logger.info(f"✅ Found receipt URL: {charge.receipt_url}")
#                     return charge.receipt_url
#                 else:
#                     logger.info(f"❌ No receipt_url on charge: {charge.id}")
#                     # Fallback: Generate dashboard URL
#                     if charge.status == 'succeeded':
#                         dashboard_url = f"https://dashboard.stripe.com/payments/{charge.id}"
#                         logger.info(f"🔧 Generated dashboard URL: {dashboard_url}")
#                         return dashboard_url
#             except Exception as ch_e:
#                 logger.error(f"❌ Error retrieving charge {payment_id}: {ch_e}")
        
#         elif payment_id.startswith('pm_'):  # Payment Method
#             logger.info(f"📋 Payment Method ID provided, skipping receipt URL retrieval: {payment_id}")
#             return None
        
#         elif payment_id.startswith('in_'):  # Invoice
#             logger.info(f"📋 Processing Invoice: {payment_id}")
#             try:
#                 invoice = stripe.Invoice.retrieve(payment_id)
#                 logger.info(f"✅ Retrieved Invoice: {invoice.id}")
#                 if invoice and invoice.invoice_pdf:
#                     logger.info(f"✅ Found invoice PDF: {invoice.invoice_pdf}")
#                     return invoice.invoice_pdf
#                 else:
#                     logger.info(f"❌ No invoice_pdf on invoice: {invoice.id}")
#             except Exception as inv_e:
#                 logger.error(f"❌ Error retrieving invoice {payment_id}: {inv_e}")
                
#         logger.info(f"❌ No receipt URL found for payment_id: {payment_id}")
#         return None
        
#     except Exception as e:
#         logger.error(f"❌ Unexpected error fetching receipt URL for payment {payment_id}: {e}")
#         return None

# def _get_stripe_receipt_url(payment_intent_id: str) -> dict[str, str | None]:
#     """Return both receipt and invoice links if available."""
#     try:
#         pi = stripe.PaymentIntent.retrieve(payment_intent_id)

#         result = {"receipt_url": None, "invoice_pdf": None}

#         if pi.latest_charge:
#             charge = stripe.Charge.retrieve(pi.latest_charge)

#             # Receipt link (always for card payments)
#             result["receipt_url"] = charge.receipt_url

#             # If linked to an invoice (subscription payments, etc.)
#             if charge.invoice:
#                 invoice = stripe.Invoice.retrieve(charge.invoice)
#                 result["invoice_pdf"] = invoice.invoice_pdf

#         return result

#     except Exception as e:
#         print(f"Error fetching links: {e}")
#         return {"receipt_url": None, "invoice_pdf": None}

def _get_stripe_receipt_url(payment_intent_id: str) -> str | None:
    try:
        # Get the PaymentIntent
        pi = stripe.PaymentIntent.retrieve(payment_intent_id)

        # Use latest_charge directly
        if pi.latest_charge:
            charge = stripe.Charge.retrieve(pi.latest_charge)

            if charge.receipt_url:
                return charge.receipt_url

            # fallback: if invoice exists
            if charge.invoice:
                invoice = stripe.Invoice.retrieve(charge.invoice)
                if invoice.invoice_pdf:
                    return invoice.invoice_pdf

        return None

    except Exception as e:
        print(f"Error fetching receipt: {e}")
        return None

# def _get_stripe_receipt_url(payment_intent_id: str, customer_email: str = None, customer_name: str = None) -> dict[str, str | None]:
#     """
#     Return receipt_url if available.
#     If no invoice exists, generate an invoice PDF as fallback.
#     """
#     try:
#         pi = stripe.PaymentIntent.retrieve(payment_intent_id)

#         result = {"receipt_url": None, "invoice_pdf": None}

#         if pi.latest_charge:
#             charge = stripe.Charge.retrieve(pi.latest_charge)
#             print("billibillibillibilli",charge,"chargechargechargechargecharge")
#             # ✅ Always get Stripe receipt
#             result["receipt_url"] = charge.receipt_url

#             # ✅ If Stripe already created an invoice (e.g. subscription payment)
#             if charge.invoice:
#                 invoice = stripe.Invoice.retrieve(charge.invoice)
#                 print("yoooo")
#                 result["invoice_pdf"] = invoice.invoice_pdf

#             # ❌ No invoice? → create one manually
#             else:
#                 # Create a Customer if not already linked
#                 customer_id = pi.customer
#                 if not customer_id:
#                     customer = stripe.Customer.create(
#                         email=customer_email or "no-email@example.com",
#                         name=customer_name or "Unknown User"
#                     )
#                     customer_id = customer.id

#                 # Create invoice item for the charge
#                 stripe.InvoiceItem.create(
#                     customer=customer_id,
#                     amount=pi.amount,  # in cents
#                     currency=pi.currency,
#                     description=pi.description or "Membership Payment"
#                 )

#                 # Create + finalize invoice
#                 invoice = stripe.Invoice.create(customer=customer_id, auto_advance=True)
#                 invoice = stripe.Invoice.finalize_invoice(invoice.id)

#                 # Now invoice has a downloadable PDF
#                 result["invoice_pdf"] = invoice.invoice_pdf

#         return result

#     except Exception as e:
#         print(f"Error fetching links: {e}")
#         return {"receipt_url": None, "invoice_pdf": None}

# def _get_stripe_receipt_url(payment_id: str, subscription_id: Optional[str] = None) -> Optional[str]:
#     try:
#         # PaymentIntent flow
#         if payment_id.startswith("pi_"):
#             pi = stripe.PaymentIntent.retrieve(payment_id, expand=["charges"])
#             if pi.charges and len(pi.charges.data) > 0:
#                 charge = pi.charges.data[0]
#                 if charge.receipt_url:
#                     return charge.receipt_url
#                 if charge.invoice:
#                     invoice = stripe.Invoice.retrieve(charge.invoice)
#                     if invoice.invoice_pdf:
#                         return invoice.invoice_pdf

#         # Charge flow
#         elif payment_id.startswith("ch_"):
#             charge = stripe.Charge.retrieve(payment_id)
#             if charge.receipt_url:
#                 return charge.receipt_url
#             if charge.invoice:
#                 invoice = stripe.Invoice.retrieve(charge.invoice)
#                 if invoice.invoice_pdf:
#                     return invoice.invoice_pdf

#         # Invoice flow
#         elif payment_id.startswith("in_"):
#             invoice = stripe.Invoice.retrieve(payment_id)
#             if invoice.invoice_pdf:
#                 return invoice.invoice_pdf

#         # Subscription fallback (get latest invoice)
#         elif subscription_id and subscription_id.startswith("sub_"):
#             invoices = stripe.Invoice.list(subscription=subscription_id, limit=1)
#             if invoices.data and invoices.data[0].invoice_pdf:
#                 return invoices.data[0].invoice_pdf

#         # PaymentMethod (pm_) → needs subscription_id or PaymentIntent
#         elif payment_id.startswith("pm_") and subscription_id:
#             invoices = stripe.Invoice.list(subscription=subscription_id, limit=1)
#             if invoices.data and invoices.data[0].invoice_pdf:
#                 return invoices.data[0].invoice_pdf

#         # Fallback
#         return f"https://dashboard.stripe.com/payments/{payment_id}"

#     except Exception as e:
#         logger.error(f"Stripe receipt fetch failed for {payment_id}: {e}")
#         return None


class OrderHistoryService:
    """Service for managing order history operations"""
    
    def __init__(self):
        self._collections = None
        self._users_collection = None
        self._payments_collection = None
        self._club_memberships_collection = None
    
    def _ensure_collections_initialized(self):
        """Lazy initialization of collections to prevent circular imports"""
        if self._collections is None:
            self._collections = get_collections()
            self._users_collection = self._collections.get_users_collection()
            self._payments_collection = self._collections.get_payments_collection()
            self._club_memberships_collection = self._collections.get_club_memberships_collection()
            self._club_payments_collection = self._collections.get_club_payments_collection()
            self._clubs_collection = self._collections.get_clubs_collection()
    
    async def get_order_history(self, user_id: str, page: int = 1, page_size: int = 10, order_type: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get complete order history for a user with pagination
        
        Args:
            user_id: User's ID
            page: Page number (starts from 1)
            page_size: Number of items per page
            order_type: Filter by order type ('platform_fee' or 'club_membership')
            
        Returns:
            Tuple[bool, Optional[Dict], Optional[str]]: (success, order_history_data, error_message)
        """
        try:
            self._ensure_collections_initialized()
            logger.info(f"Getting order history for user {user_id}")
            
            # Get user data first
            user = await self._users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False, None, "User not found"
            
            # Validate user role
            user_role = user.get("role")
            if user_role not in ["Member", "Captain"]:
                return False, None, "Only Members and Captains can view order history"
            
            # Get platform fee payments (from payments table)
            platform_fees = await self._get_platform_fee_payments(user_id, user)
            print("platform_fees",platform_fees)
            
            # Get club membership payments (from club_memberships table) - for Members
            club_memberships = []
            if user_role == "Member":
                club_memberships = await self._get_club_membership_payments(user_id, user)
                logger.info(f"Retrieved {len(platform_fees)} platform fees and {len(club_memberships)} club memberships for Member")
            else:
                logger.info(f"Retrieved {len(platform_fees)} platform fees for Captain")
            
            # Get club payments (from club_payments table) - for Captains
            club_payments = []
            if user_role == "Captain":
                club_payments = await self._get_club_payments(user_id, user)
                logger.info(f"Retrieved {len(platform_fees)} platform fees and {len(club_payments)} club payments for Captain")
            
            # Combine all orders
            all_orders = []
            
            # Add platform fees if not filtering or if filtering for platform_fee
            if not order_type or order_type == "platform_fee":
                all_orders.extend(platform_fees)
            
            # Add club memberships if not filtering or if filtering for club_membership (for Members)
            if not order_type or order_type == "club_membership":
                all_orders.extend(club_memberships)
            
            # Add club payments if not filtering or if filtering for club_payment (for Captains)
            if not order_type or order_type == "club_payment":
                all_orders.extend(club_payments)
            
            # Sort all orders by payment date (newest first)
            all_orders.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)
            
            # Calculate pagination
            total_orders = len(all_orders)
            total_pages = (total_orders + page_size - 1) // page_size  # Ceiling division
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_orders = all_orders[start_index:end_index]
            
            # Calculate summary statistics
            total_platform_fees = sum(order["amount"] for order in platform_fees)
            total_club_memberships = sum(order["amount"] for order in club_memberships)
            total_club_payments = sum(order["amount"] for order in club_payments)
            total_amount = total_platform_fees + total_club_memberships + total_club_payments
            
            order_history_data = {
                "user_id": user_id,
                "user_name": user.get("full_name", "Unknown"),
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    "total_orders": total_orders,
                    "has_next_page": page < total_pages,
                    "has_previous_page": page > 1
                },
                "total_amount": total_amount,
                "platform_fees_count": len(platform_fees),
                "platform_fees_total": total_platform_fees,
                "club_memberships_count": len(club_memberships),
                "club_memberships_total": total_club_memberships,
                "club_payments_count": len(club_payments),
                "club_payments_total": total_club_payments,
                "user_role": user_role,
                "orders": paginated_orders,
                "retrieved_at": datetime.now(timezone.utc).isoformat()
            }
            
            logger.info(f"Retrieved {len(all_orders)} orders for user {user_id}")
            return True, order_history_data, None
            
        except Exception as e:
            error_msg = f"Error getting order history: {str(e)}"
            logger.error(error_msg)
            return False, None, error_msg
    
    async def _get_platform_fee_payments(self, user_id: str, user_data: Dict) -> List[Dict[str, Any]]:
        """Get platform fee payments from payments table"""
        try:
            # Query payments table for platform fees
            payments_cursor = self._payments_collection.find({
                "user_id": user_id,
                "payment_type": "subscription"  # Platform fees are subscription payments
            }).sort("created_at", -1)
            
            platform_fees = []
            async for payment in payments_cursor:
                # Get status and membership_status from users table
                user_status = user_data.get("status", "unknown")
                user_membership_status = user_data.get("membership_status", "unknown")
                
                # Convert amount from cents to dollars if needed
                amount = payment.get("amount", 0)
                if amount > 100:  # Assume amounts > 100 are in cents
                    amount = amount 
                
                # Get receipt URL from Stripe
                payment_id = payment.get("payment_method_id")
                logger.info(f"🔍 Platform fee payment_id: {payment_id}")
                
                # Test Stripe connectivity first
                try:
                    logger.info(f"🔧 Testing Stripe connectivity...")
                    stripe.api_key  # This will raise an error if not set
                    logger.info(f"✅ Stripe API key is configured")
                except Exception as stripe_error:
                    logger.error(f"❌ Stripe configuration error: {stripe_error}")
                
                receipt_url = _get_stripe_receipt_url(payment_id) if payment_id else None
                logger.info(f"🔍 Platform fee receipt_url: {receipt_url}")
                
                order_item = {
                    "order_id": str(payment.get("_id")),
                    "order_type": "platform_fee",
                    "payment_date": payment.get("created_at").isoformat() if payment.get("created_at") else "",
                    "membership_type": payment.get("membership_type", "unknown"),
                    "amount": amount,
                    "currency": payment.get("currency", "usd"),
                    "status": user_status,
                    "membership_status": user_membership_status,
                    "payment_id": payment_id,
                    "subscription_id": payment.get("subscription_id"),
                    "pricing_plan": None,
                    "payment_method": payment.get("payment_method", "Card"),
                    "receipt_url": receipt_url,
                    "start_date": None,
                    "end_date": None,
                    "created_at": payment.get("created_at").isoformat() if payment.get("created_at") else "",
                    "updated_at": payment.get("updated_at").isoformat() if payment.get("updated_at") else ""
                }
                platform_fees.append(order_item)
            
            logger.info(f"Found {len(platform_fees)} platform fee payments for user {user_id}")
            return platform_fees
            
        except Exception as e:
            logger.error(f"Error getting platform fee payments: {e}")
            return []
    
    async def _get_club_membership_payments(self, user_id: str, user_data: Dict) -> List[Dict[str, Any]]:
        """Get club membership payments from club_memberships table"""
        try:
            logger.info(f"Querying club memberships for user_id: {user_id} (type: {type(user_id)})")
            
            # Test collection access
            total_collection_count = await self._club_memberships_collection.count_documents({})
            logger.info(f"Total documents in club_memberships collection: {total_collection_count}")
            
            # Try to convert user_id to ObjectId and log any issues
            try:
                user_object_id = ObjectId(user_id)
                logger.info(f"Converted user_id to ObjectId: {user_object_id}")
            except Exception as e:
                logger.error(f"Failed to convert user_id to ObjectId: {e}")
                return []
            
            # Also try a string query to see if that works
            logger.info(f"Also trying string query for user_id: {user_id}")
            string_count = await self._club_memberships_collection.count_documents({
                "user_id": user_id
            })
            logger.info(f"String query count: {string_count}")
            
            # Let's also check what the actual user_id looks like in the database
            logger.info("Checking a few club membership documents to see user_id format...")
            sample_docs = await self._club_memberships_collection.find({}).limit(3).to_list(length=None)
            for i, doc in enumerate(sample_docs):
                doc_user_id = doc.get('user_id')
                logger.info(f"Sample doc {i+1}: user_id type={type(doc_user_id)}, value={doc_user_id}")
            
            # First, count how many documents should be returned
            total_count = await self._club_memberships_collection.count_documents({
                "user_id": user_object_id
            })
            logger.info(f"Total club memberships found for user {user_id}: {total_count}")
            
            # Query club_memberships table - try both ObjectId and string formats
            query_filter = {"user_id": user_object_id}
            logger.info(f"Query filter (ObjectId): {query_filter}")
            
            memberships_cursor = self._club_memberships_collection.find(query_filter).sort("created_at", -1)
            
            # Convert cursor to list first to see all documents
            all_memberships = await memberships_cursor.to_list(length=None)
            logger.info(f"Retrieved {len(all_memberships)} club membership documents from ObjectId query")
            
            # If ObjectId query returns fewer results than expected, try string query
            if len(all_memberships) < total_count:
                logger.info(f"ObjectId query returned {len(all_memberships)} results, but count shows {total_count}. Trying string query...")
                string_cursor = self._club_memberships_collection.find({"user_id": user_id}).sort("created_at", -1)
                all_memberships = await string_cursor.to_list(length=None)
                logger.info(f"String query retrieved {len(all_memberships)} club membership documents")
            
            club_memberships = []
            membership_count = 0
            
            for membership in all_memberships:
                membership_count += 1
                logger.info(f"Processing club membership {membership_count}: {membership.get('club_name', 'Unknown')} (ID: {membership.get('_id')})")
                
                # Get status and membership_status from clubs_joined array in users table
                club_id = str(membership.get("club_id"))
                club_name = membership.get("club_name", "Unknown Club")
                
                # Find the club in user's clubs_joined array
                clubs_joined = user_data.get("clubs_joined", [])
                club_status = "unknown"  # Initialize club_status
                club_membership_status = "unknown"
                
                logger.info(f"Processing club membership {i+1}: {club_name} (ID: {membership.get('_id')})")
                logger.info(f"Looking for club_id {club_id} in clubs_joined array (length: {len(clubs_joined)})")
                
                for club in clubs_joined:
                    if str(club.get("club_id")) == club_id:
                        club_status = club.get("status", "unknown")
                        club_membership_status = club.get("membership_status", "unknown")
                        logger.info(f"Found club in clubs_joined: status={club_status}, membership_status={club_membership_status}")
                        break
                else:
                    logger.info(f"Club {club_id} not found in clubs_joined array")
                
                # Convert amount from cents to dollars if needed
                amount = membership.get("amount_paid", 0)
                if amount > 100:  # Assume amounts > 100 are in cents
                    amount = amount
                
                # Get receipt URL from Stripe
                payment_id = membership.get("payment_id")
                logger.info(f"Club membership payment_id: {payment_id}")
                receipt_url = _get_stripe_receipt_url(payment_id) if payment_id else None
                logger.info(f"Club membership receipt_url: {receipt_url}")
                
                order_item = {
                    "order_id": str(membership.get("_id")),
                    "order_type": "club_membership",
                    "payment_date": membership.get("created_at").isoformat() if membership.get("created_at") else "",
                    "membership_type": membership.get("membership_type", "unknown"),
                    "amount": amount,
                    "currency": "usd",  # Default currency
                    "status": club_status,
                    "membership_status": club_membership_status,
                    "club_name": club_name,
                    "club_id": club_id,
                    "payment_id": payment_id,
                    "subscription_id": None,
                    "pricing_plan": membership.get("pricing_plan"),
                    "payment_method": membership.get("payment_method", "Card"),
                    "receipt_url": receipt_url,
                    "start_date": membership.get("start_date").isoformat() if membership.get("start_date") else None,
                    "end_date": membership.get("end_date").isoformat() if membership.get("end_date") else None,
                    "created_at": membership.get("created_at").isoformat() if membership.get("created_at") else "",
                    "updated_at": membership.get("updated_at").isoformat() if membership.get("updated_at") else ""
                }
                club_memberships.append(order_item)
                logger.info(f"Successfully added club membership: {club_name}")
            
            logger.info(f"Found {len(club_memberships)} club membership payments for user {user_id} (processed {membership_count} total records)")
            return club_memberships
            
        except Exception as e:
            logger.error(f"Error getting club membership payments: {e}")
            return []
    
    async def _get_club_payments(self, user_id: str, user_data: Dict) -> List[Dict[str, Any]]:
        """Get club payments from club_payments table for Captains"""
        try:
            logger.info(f"Querying club payments for Captain user_id: {user_id}")
            
            # Test collection access
            total_collection_count = await self._club_payments_collection.count_documents({})
            logger.info(f"Total documents in club_payments collection: {total_collection_count}")
            
            # Try to convert user_id to ObjectId and log any issues
            try:
                user_object_id = ObjectId(user_id)
                logger.info(f"Converted user_id to ObjectId: {user_object_id}")
            except Exception as e:
                logger.error(f"Failed to convert user_id to ObjectId: {e}")
                return []
            
            # Query club_payments table
            query_filter = {"user_id": user_object_id}
            logger.info(f"Query filter for club_payments: {query_filter}")
            
            # Count how many documents should be returned
            total_count = await self._club_payments_collection.count_documents(query_filter)
            logger.info(f"Total club payments found for Captain {user_id}: {total_count}")
            
            # Query club_payments table
            payments_cursor = self._club_payments_collection.find(query_filter).sort("created_at", -1)
            
            # Convert cursor to list first to see all documents
            all_payments = await payments_cursor.to_list(length=None)
            logger.info(f"Retrieved {len(all_payments)} club payment documents from cursor")
            
            club_payments = []
            payment_count = 0
            
            for payment in all_payments:
                payment_count += 1
                logger.info(f"Processing club payment {payment_count}: {payment.get('club_name', 'Unknown')} (ID: {payment.get('_id')})")
                
                # Get club status from clubs table
                club_id = str(payment.get("club_id"))
                club_name = payment.get("club_name", "Unknown Club")
                
                # Query clubs table to get club status
                club_status = "unknown"
                try:
                    club = await self._clubs_collection.find_one({"_id": ObjectId(club_id)})
                    if club:
                        club_status = club.get("status", "unknown")
                        logger.info(f"Found club status for {club_name}: {club_status}")
                    else:
                        logger.warning(f"Club not found for club_id: {club_id}")
                except Exception as e:
                    logger.error(f"Error querying clubs table for club_id {club_id}: {e}")
                
                # Convert amount from cents to dollars if needed
                amount = payment.get("amount_paid", 0)
                if amount > 100:  # Assume amounts > 100 are in cents
                    amount = amount 
                
                # Get receipt URL from Stripe
                payment_id = payment.get("payment_intent_id")
                receipt_url = _get_stripe_receipt_url(payment_id) if payment_id else None
                
                order_item = {
                    "order_id": str(payment.get("_id")),
                    "order_type": "club_payment",
                    "payment_date": payment.get("created_at").isoformat() if payment.get("created_at") else "",
                    "membership_type": "captain",  # Captains have captain membership type
                    "amount": amount,
                    "currency": "usd",  # Default currency
                    "status": club_status,  # Status from clubs table
                    "membership_status": "active",  # Captains are always active
                    "club_name": club_name,
                    "club_id": club_id,
                    "payment_id": payment_id,
                    "subscription_id": None,
                    "pricing_plan": payment.get("pricing_plan"),
                    "payment_method": payment.get("payment_method", "Card"),
                    "receipt_url": receipt_url,
                    "start_date": payment.get("start_date").isoformat() if payment.get("start_date") else None,
                    "end_date": payment.get("end_date").isoformat() if payment.get("end_date") else None,
                    "created_at": payment.get("created_at").isoformat() if payment.get("created_at") else "",
                    "updated_at": payment.get("updated_at").isoformat() if payment.get("updated_at") else ""
                }
                club_payments.append(order_item)
                logger.info(f"Successfully added club payment: {club_name}")
            
            logger.info(f"Found {len(club_payments)} club payments for Captain {user_id} (processed {payment_count} total records)")
            return club_payments
            
        except Exception as e:
            logger.error(f"Error getting club payments: {e}")
            return []

    async def _get_admin_order_history(self, admin_email: str, page: int, page_size: int, order_type: Optional[str]) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get order history for admin users.
        
        Admins don't have personal order history, but they can view system-wide statistics
        or their own admin-related transactions if any.
        
        Args:
            admin_email: Admin's email address
            page: Page number
            page_size: Number of items per page
            order_type: Filter by order type
            
        Returns:
            Tuple[bool, Optional[Dict], Optional[str]]: (success, order_history_data, error_message)
        """
        try:
            logger.info(f"Getting admin order history for {admin_email}")
            
            # For now, return empty order history for admins
            # In the future, this could include admin-specific transactions or system statistics
            
            empty_order_history = {
                "orders": [],
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_orders": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_previous": False
                },
                "summary": {
                    "total_platform_fees": 0.0,
                    "total_club_memberships": 0.0,
                    "total_club_payments": 0.0,
                    "total_amount": 0.0,
                    "platform_fee_count": 0,
                    "club_membership_count": 0,
                    "club_payment_count": 0,
                    "total_order_count": 0
                },
                "user_info": {
                    "user_id": admin_email,
                    "email": admin_email,
                    "role": "Admin",
                    "status": "active",
                    "membership_status": "admin"
                }
            }
            
            logger.info(f"Returning empty order history for admin {admin_email}")
            return True, empty_order_history, None
            
        except Exception as e:
            logger.error(f"Error getting admin order history: {e}")
            return False, None, f"Error retrieving admin order history: {str(e)}"

# Global service instance with lazy initialization
_order_history_service: OrderHistoryService = None

def get_order_history_service() -> OrderHistoryService:
    """Get the global order history service instance"""
    global _order_history_service
    if _order_history_service is None:
        _order_history_service = OrderHistoryService()
    return _order_history_service
