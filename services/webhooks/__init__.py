"""
Unified Webhook Service

This module provides a centralized webhook handler for all Stripe events.
"""

from .routes import router

__all__ = ['router']


