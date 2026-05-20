# import stripe
# from core.utils.price_config import PriceConfig, CurrencyConfig
# import os
# # Initialize Stripe
# stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')


# # Store the product IDs somewhere persistent (DB, env)
# PRODUCTS = {
#     "member": {"product_id": None, "price_id": None, "amount": PriceConfig.MEMBER_ROLE_AMOUNT, "type": "one_time"},
#     "captain": {"product_id": None, "price_id": None, "amount": PriceConfig.CAPTAIN_ROLE_AMOUNT, "type": "recurring", "interval": "month"},
#     "moderator": {"product_id": None, "price_id": None, "amount": PriceConfig.ADDITIONAL_MODERATION_AMOUNT, "type": "recurring", "interval": "month"}
# }


# def create_or_update_product(name: str, role: str):
#     """
#     Ensure Stripe product and price exist for a role.
#     Only create if missing or price changed.
#     """
#     product_info = PRODUCTS[role]
#     existing_product_id = product_info.get("product_id")
#     amount_cents = int(product_info["amount"] * 100)

#     # 🔹 1. Try to find an existing product by name
#     if not existing_product_id:
#         existing_products = stripe.Product.list(active=True, limit=100)
#         for p in existing_products.data:
#             if p.name == name:
#                 product_info["product_id"] = p.id
#                 existing_product_id = p.id
#                 print(f"Found existing product for {role}: {p.id}")
#                 break

#     # 🔹 2. Retrieve or create product
#     product = None
#     if existing_product_id:
#         try:
#             product = stripe.Product.retrieve(existing_product_id)
#         except stripe.error.InvalidRequestError:
#             product = None

#     if not product:
#         product = stripe.Product.create(
#             name=name,
#             description=f"{role.capitalize()} subscription",
#         )
#         product_info["product_id"] = product.id
#         print(f"Created product for {role}: {product.id}")

#     # 🔹 3. Check if price already exists for this product
#     existing_price = None
#     prices = stripe.Price.list(product=product.id, active=True, limit=100)

#     for p in prices.data:
#         if (
#             p.unit_amount == amount_cents
#             and p.currency == CurrencyConfig.DEFAULT_CURRENCY
#         ):
#             # For recurring, also check interval match
#             if product_info["type"] == "recurring":
#                 if p.recurring and p.recurring.interval == product_info["interval"]:
#                     existing_price = p
#                     break
#             else:
#                 if not p.recurring:
#                     existing_price = p
#                     break

#     # 🔹 4. Reuse or create price
#     if existing_price:
#         product_info["price_id"] = existing_price.id
#         print(f"Found existing price for {role}: {existing_price.id}")
#     else:
#         if product_info["type"] == "one_time":
#             price = stripe.Price.create(
#                 product=product.id,
#                 unit_amount=amount_cents,
#                 currency=CurrencyConfig.DEFAULT_CURRENCY,
#             )
#         else:
#             price = stripe.Price.create(
#                 product=product.id,
#                 unit_amount=amount_cents,
#                 currency=CurrencyConfig.DEFAULT_CURRENCY,
#                 recurring={"interval": product_info["interval"]},
#             )
#         product_info["price_id"] = price.id
#         print(f"Created price for {role}: {price.id}")



# # if __name__ == "__main__":
# #     # Run once to ensure products/prices exist
# #     create_or_update_product("MVP Sports Membership - Member", "member")
# #     create_or_update_product("MVP Sports Membership - Captain", "captain")
# #     create_or_update_product("MVP Sports Membership - Moderator", "moderator")

# #     print("✅ Stripe products/prices verified/created successfully.")


import stripe
import os
import json
from core.utils.price_config import PriceConfig, CurrencyConfig

stripe.api_key = os.getenv(
    'STRIPE_SECRET_KEY',
    ''
)

# Path where product/price data will be stored
STRIPE_PRODUCTS_FILE = os.path.join(os.path.dirname(__file__), "stripe_products.json")

# Default product definitions
PRODUCTS = {
    "member": {"product_id": None, "price_id": None, "amount": PriceConfig.MEMBER_ROLE_AMOUNT, "type": "one_time"},
    "captain": {"product_id": None, "price_id": None, "amount": PriceConfig.CAPTAIN_ROLE_AMOUNT, "type": "recurring", "interval": "month"},
    "moderator": {"product_id": None, "price_id": None, "amount": PriceConfig.ADDITIONAL_MODERATION_AMOUNT, "type": "recurring", "interval": "month"},
}


def load_products_from_file():
    """Load saved Stripe product/price data if exists."""
    if os.path.exists(STRIPE_PRODUCTS_FILE):
        try:
            with open(STRIPE_PRODUCTS_FILE, "r") as f:
                saved_data = json.load(f)
                for role, data in saved_data.items():
                    if role in PRODUCTS:
                        PRODUCTS[role].update(data)
            print("📦 Loaded existing Stripe product data from file.")
        except Exception as e:
            print(f"⚠️ Failed to load stripe_products.json: {e}")


def save_products_to_file():
    """Persist the Stripe product/price info to JSON file."""
    try:
        with open(STRIPE_PRODUCTS_FILE, "w") as f:
            json.dump(PRODUCTS, f, indent=4)
        print(f"💾 Saved Stripe product info to {STRIPE_PRODUCTS_FILE}")
    except Exception as e:
        print(f"❌ Failed to save Stripe product data: {e}")


def create_or_update_product(name: str, role: str):
    """Ensure Stripe product and price exist for a role."""
    product_info = PRODUCTS[role]
    existing_product_id = product_info.get("product_id")
    amount_cents = int(product_info["amount"] * 100)

    # 1️⃣ Try to find existing product by name
    if not existing_product_id:
        existing_products = stripe.Product.list(active=True, limit=100)
        for p in existing_products.data:
            if p.name == name:
                product_info["product_id"] = p.id
                existing_product_id = p.id
                print(f"Found existing product for {role}: {p.id}")
                break

    # 2️⃣ Retrieve or create product
    product = None
    if existing_product_id:
        try:
            product = stripe.Product.retrieve(existing_product_id)
        except stripe.error.InvalidRequestError:
            product = None

    if not product:
        product = stripe.Product.create(
            name=name,
            description=f"{role.capitalize()} subscription",
        )
        product_info["product_id"] = product.id
        print(f"Created product for {role}: {product.id}")

    # 3️⃣ Check existing price for this product
    existing_price = None
    prices = stripe.Price.list(product=product.id, active=True, limit=100)
    for p in prices.data:
        if (
            p.unit_amount == amount_cents
            and p.currency == CurrencyConfig.DEFAULT_CURRENCY
        ):
            if product_info["type"] == "recurring":
                if p.recurring and p.recurring.interval == product_info["interval"]:
                    existing_price = p
                    break
            else:
                if not p.recurring:
                    existing_price = p
                    break

    # 4️⃣ Create or reuse price
    if existing_price:
        product_info["price_id"] = existing_price.id
        print(f"Found existing price for {role}: {existing_price.id}")
    else:
        if product_info["type"] == "one_time":
            price = stripe.Price.create(
                product=product.id,
                unit_amount=amount_cents,
                currency=CurrencyConfig.DEFAULT_CURRENCY,
            )
        else:
            price = stripe.Price.create(
                product=product.id,
                unit_amount=amount_cents,
                currency=CurrencyConfig.DEFAULT_CURRENCY,
                recurring={"interval": product_info["interval"]},
            )
        product_info["price_id"] = price.id
        print(f"Created new price for {role}: {price.id}")


def initialize_stripe_products():
    """Main entry: load from file, ensure products/prices exist, and save."""
    load_products_from_file()

    create_or_update_product("MVP Sports Membership - Member", "member")
    create_or_update_product("MVP Sports Membership - Captain", "captain")
    create_or_update_product("MVP Sports Membership - Moderator", "moderator")

    save_products_to_file()
    print("✅ Stripe products/prices verified and saved successfully.")
