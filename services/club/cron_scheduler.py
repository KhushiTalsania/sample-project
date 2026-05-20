"""
Cron Job Scheduler for Trial Membership Expiration

This module sets up and manages scheduled tasks for checking
and expiring trial memberships.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .trial_expiration_cron import get_trial_expiration_service

logger = logging.getLogger(__name__)


class TrialExpirationScheduler:
    """Scheduler for trial expiration cron jobs"""
    
    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.expiration_service = get_trial_expiration_service()
        self.is_running = False
    
    def start(self):
        """Start the scheduler"""
        try:
            if self.is_running:
                logger.warning("Scheduler is already running")
                return
            
            self.scheduler = AsyncIOScheduler()
            
            # ============================================
            # TESTING MODE: Run every 2 minutes for testing
            # # ============================================
            # self.scheduler.add_job(
            #     self._run_expiration_check,
            #     trigger=IntervalTrigger(minutes=2),  # Run every 2 minutes for testing
            #     id='trial_expiration_testing',
            #     name='Check and expire trial memberships (TESTING - every 2 minutes)',
            #     replace_existing=True
            # )
            
            # ============================================
            # PRODUCTION MODE (Uncomment for production)
            # ============================================
            # Option 1: Run every hour
            # self.scheduler.add_job(
            #     self._run_expiration_check,
            #     trigger=IntervalTrigger(hours=1),
            #     id='trial_expiration_hourly',
            #     name='Check and expire trial memberships (hourly)',
            #     replace_existing=True
            # )
            
            # Option 2: Run at 2 AM daily
            self.scheduler.add_job(
                self._run_expiration_check,
                trigger=CronTrigger(hour=2, minute=0),
                id='trial_expiration_daily',
                name='Check and expire trial memberships (daily)',
                replace_existing=True
            )
            
            self.scheduler.start()
            self.is_running = True
            
            logger.info("✅ Trial expiration scheduler started successfully")
            logger.info("⚠️ TESTING MODE: Expiration checks will run every 2 minutes")
            logger.info("⚠️ Remember to switch to production mode after testing!")
            
        except Exception as e:
            logger.error(f"❌ Error starting scheduler: {e}")
            raise
    
    def stop(self):
        """Stop the scheduler"""
        try:
            if self.scheduler and self.is_running:
                self.scheduler.shutdown()
                self.is_running = False
                logger.info("✅ Trial expiration scheduler stopped")
        except Exception as e:
            logger.error(f"❌ Error stopping scheduler: {e}")
    
    async def _run_expiration_check(self):
        """Run the expiration check (called by scheduler)"""
        try:
            now = datetime.now(timezone.utc)
            logger.info(f"🔄 Running trial expiration check at {now.isoformat()}")
            
            result = await self.expiration_service.check_and_expire_trial_memberships()
            
            if result.get("success"):
                logger.info(f"✅ Expiration check completed: {result.get('message')}")
            else:
                logger.error(f"❌ Expiration check failed: {result.get('message')}")
                
        except Exception as e:
            logger.error(f"❌ Error in expiration check: {e}")
    
    async def run_manual_check(self):
        """Manually trigger an expiration check (for testing or admin use)"""
        try:
            logger.info("🔧 Manual expiration check triggered")
            result = await self.expiration_service.check_and_expire_trial_memberships()
            return result
        except Exception as e:
            logger.error(f"❌ Error in manual expiration check: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "expired_count": 0
            }


# Global scheduler instance
_scheduler = None


def get_trial_scheduler() -> TrialExpirationScheduler:
    """Get or create scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = TrialExpirationScheduler()
    return _scheduler


def start_trial_expiration_scheduler():
    """Start the trial expiration scheduler (call on app startup)"""
    try:
        scheduler = get_trial_scheduler()
        scheduler.start()
        logger.info("✅ Trial expiration scheduler initialized")
    except Exception as e:
        logger.error(f"❌ Failed to start trial expiration scheduler: {e}")


def stop_trial_expiration_scheduler():
    """Stop the trial expiration scheduler (call on app shutdown)"""
    try:
        scheduler = get_trial_scheduler()
        scheduler.stop()
        logger.info("✅ Trial expiration scheduler stopped")
    except Exception as e:
        logger.error(f"❌ Failed to stop trial expiration scheduler: {e}")
