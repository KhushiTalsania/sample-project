"""
Price Configuration

This module contains price-related constants for the application.
"""


# Payment amounts in USD
class PriceConfig:
    """Price configuration constants"""

    # Additional moderation amount
    ADDITIONAL_MODERATION_AMOUNT = 9.95

    # Captain role amount (monthly subscription)
    CAPTAIN_ROLE_AMOUNT = 99.00

    # Member amount (monthly subscription)
    MEMBER_ROLE_AMOUNT = 19.95


# Currency configuration
class CurrencyConfig:
    """Currency configuration constants"""

    DEFAULT_CURRENCY = "usd"
    CURRENCY_SYMBOL = "$"
