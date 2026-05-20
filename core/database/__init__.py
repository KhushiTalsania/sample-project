"""
Centralized Database Module

This module provides unified database connections and utilities for all services.
It eliminates the need for duplicate database configurations across microservices.
"""

from .connection import DatabaseManager, get_database_manager
from .collections import Collections

__all__ = ["DatabaseManager", "get_database_manager", "Collections"] 