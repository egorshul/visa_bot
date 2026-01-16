"""
Main bot logic module.

Orchestrates the slot checking process with scheduling, retries, and notifications.
"""

import asyncio
import random
import signal
import sys
from datetime import datetime, time
from typing import List, Optional

from .browser import BrowserManager
from .captcha import CaptchaSolver
from .notifications import TelegramNotifier, EmailNotifier
from .notifications.telegram import SlotInfo as TelegramSlotInfo
from .utils.config import Config
from .utils.logger import BotLogger, setup_logger
from .vfs_navigator import VFSNavigator, PageState, SlotInfo

logger = BotLogger("Bot")


class VisaSlotBot:
    """
    Main bot class that orchestrates slot checking.
    """

    def __init__(self, config: Config):
        """
        Initialize the bot.

        Args:
            config: Configuration instance
        """
        self.config = config
        self._running = False
        self._shutdown_requested = False

        # Statistics
        self._checks_count = 0
        self._errors_count = 0
        self._consecutive_errors = 0
        self._last_check_time: Optional[datetime] = None
        self._slots_found_count = 0
        self._start_time: Optional[datetime] = None

        # Components (initialized in start())
        self._browser: Optional[BrowserManager] = None
        self._navigator: Optional[VFSNavigator] = None
        self._captcha_solver: Optional[CaptchaSolver] = None
        self._telegram: Optional[TelegramNotifier] = None
        self._email: Optional[EmailNotifier] = None

    async def _initialize_components(self) -> None:
        """Initialize all bot components."""
        logger.info("Initializing components...")

        # Setup logging
        setup_logger(
            level=self.config.log_level,
            log_file=self.config.log_file if self.config.get("logging.file_logging", True) else None,
            max_size_mb=self.config.log_max_size,
            backup_count=self.config.log_backup_count,
            console_output=self.config.console_logging,
        )

        # Initialize browser
        self._browser = BrowserManager(self.config)

        # Initialize CAPTCHA solver
        if self.config.captcha_auto_solve:
            self._captcha_solver = CaptchaSolver(
                service=self.config.captcha_service,
                api_key=self.config.captcha_api_key,
                timeout=self.config.captcha_timeout,
                auto_solve=True,
            )
        else:
            self._captcha_solver = CaptchaSolver(auto_solve=False)

        # Initialize notifications
        if self.config.telegram_enabled:
            self._telegram = TelegramNotifier(
                bot_token=self.config.telegram_bot_token,
                chat_id=self.config.telegram_chat_id,
                enabled=True,
                notify_on=self.config.telegram_notify_on,
            )

        if self.config.email_enabled:
            self._email = EmailNotifier.from_config({
                **self.config.email_config,
                "enabled": True,
            })

        logger.info("Components initialized")

    async def start(self) -> None:
        """Start the bot."""
        logger.info("=" * 50)
        logger.info("VFS Visa Slot Checker Bot Starting")
        logger.info("=" * 50)

        # Validate configuration
        errors = self.config.validate()
        if errors:
            for error in errors:
                logger.error(f"Configuration error: {error}")
            raise ValueError("Configuration validation failed")

        # Initialize components
        await self._initialize_components()

        # Set up signal handlers
        self._setup_signal_handlers()

        # Start browser
        await self._browser.start()

        # Initialize navigator
        self._navigator = VFSNavigator(
            browser_manager=self._browser,
            config=self.config,
            captcha_solver=self._captcha_solver,
        )

        self._running = True
        self._start_time = datetime.now()

        # Send start notification
        if self._telegram:
            await self._telegram.notify_started(self.config.centers)

        logger.info(f"Monitoring centers: {', '.join(self.config.centers)}")
        logger.info(f"Check interval: {self.config.min_interval}-{self.config.max_interval}s")

        # Start main loop
        try:
            await self._main_loop()
        except Exception as e:
            logger.exception("Fatal error in main loop", e)
            raise
        finally:
            await self._cleanup()

    async def _main_loop(self) -> None:
        """Main checking loop."""
        while self._running and not self._shutdown_requested:
            try:
                # Check if within active hours
                if not self._is_within_active_hours():
                    logger.info("Outside active hours, sleeping...")
                    await asyncio.sleep(60)
                    continue

                # Check all combinations (Moscow, Moscow PRIME, Nizhniy Novgorod)
                # This is now handled in a single call to check_all_combinations
                await self._check_all_combinations()

                # Update last check time
                self._last_check_time = datetime.now()
                self._checks_count += 1

                # Send daily status if enabled
                if self._telegram and self._checks_count % 100 == 0:
                    await self._telegram.notify_status(
                        self._checks_count,
                        self._errors_count,
                        self._last_check_time,
                    )

                # Wait for next check
                wait_time = self._get_next_interval()
                logger.waiting(wait_time)
                await asyncio.sleep(wait_time)

            except asyncio.CancelledError:
                logger.info("Main loop cancelled")
                break
            except Exception as e:
                await self._handle_error(e)

    async def _check_all_combinations(self) -> None:
        """
        Check all combinations of centers and visa types.
        Calls navigator.check_all_combinations() which handles:
        - Moscow + All kind of other short stay visas
        - Moscow + PRIME TIME
        - Nizhniy Novgorod + All kind of other short stay visas
        """
        try:
            result = await self._navigator.check_all_combinations()

            if result.state == PageState.SLOT_SELECTION and result.slots:
                # Slots found!
                await self._handle_slots_found(result.slots)
                self._consecutive_errors = 0

            elif result.state == PageState.NO_SLOTS:
                logger.info("No slots found for any combination")
                self._consecutive_errors = 0

            elif result.state == PageState.BLOCKED:
                # BLOCKED by VFS - stop bot immediately
                logger.error(f"BLOCKED by VFS: {result.error_message}")
                if self._telegram:
                    await self._telegram.notify_error(
                        "🚫 BLOCKED by VFS!",
                        f"Reason: {result.error_message}\n\nBot stopped to avoid further detection. "
                        "Wait several hours before trying again with a new session.",
                    )
                # Stop the bot
                self._shutdown_requested = True
                self._running = False

            elif result.state == PageState.CAPTCHA:
                logger.warning("CAPTCHA detected")
                if self._telegram:
                    await self._telegram.notify_captcha(self._browser.page.url)
                # Wait before retry
                await asyncio.sleep(60)

            elif result.state == PageState.ERROR:
                raise Exception(result.error_message)

            elif result.state == PageState.QUEUE:
                logger.info("Queue detected")
                self._consecutive_errors = 0

        except Exception as e:
            logger.exception("Error checking combinations", e)
            self._consecutive_errors += 1
            self._errors_count += 1

            # Check if too many consecutive errors
            if self._consecutive_errors >= self.config.max_consecutive_errors:
                await self._handle_too_many_errors()

    async def _check_center(self, center: str) -> None:
        """
        Check slots for a specific center.

        Args:
            center: Center name to check
        """
        try:
            result = await self._navigator.check_slots_for_center(center)

            if result.state == PageState.SLOT_SELECTION and result.slots:
                # Slots found!
                await self._handle_slots_found(result.slots)
                self._consecutive_errors = 0

            elif result.state == PageState.NO_SLOTS:
                logger.no_slots(center)
                self._consecutive_errors = 0

            elif result.state == PageState.CAPTCHA:
                logger.warning("CAPTCHA detected")
                if self._telegram:
                    await self._telegram.notify_captcha(self._browser.page.url)
                # Wait before retry
                await asyncio.sleep(60)

            elif result.state == PageState.ERROR:
                raise Exception(result.error_message)

            elif result.state == PageState.QUEUE:
                logger.info(f"Queue detected for {center}")
                self._consecutive_errors = 0

        except Exception as e:
            logger.exception(f"Error checking {center}", e)
            self._consecutive_errors += 1
            self._errors_count += 1

            # Check if too many consecutive errors
            if self._consecutive_errors >= self.config.max_consecutive_errors:
                await self._handle_too_many_errors()

    async def _handle_slots_found(self, slots: List[SlotInfo]) -> None:
        """
        Handle found slots - send notifications.

        Args:
            slots: List of found slots
        """
        self._slots_found_count += len(slots)

        for slot in slots:
            logger.slot_found(slot.center, slot.date, ", ".join(slot.time_slots))

            # Send Telegram notification
            if self._telegram:
                telegram_slot = TelegramSlotInfo(
                    center=slot.center,
                    date=slot.date,
                    time_slots=slot.time_slots,
                    booking_url=slot.booking_url,
                )
                await self._telegram.notify_slot_available(telegram_slot)

            # Send email notification
            if self._email:
                from .notifications.email import SlotInfo as EmailSlotInfo
                email_slot = EmailSlotInfo(
                    center=slot.center,
                    date=slot.date,
                    time_slots=slot.time_slots,
                    booking_url=slot.booking_url,
                )
                await self._email.notify_slot_available(email_slot)

        # Take screenshot
        try:
            await self._navigator.take_screenshot("slots_found")
        except Exception:
            pass

    async def _handle_error(self, error: Exception) -> None:
        """
        Handle errors during checking.

        Args:
            error: The exception that occurred
        """
        self._errors_count += 1
        self._consecutive_errors += 1

        logger.exception("Error during check", error)

        # Notify about error
        if self._telegram:
            await self._telegram.notify_error(
                str(error),
                f"Consecutive errors: {self._consecutive_errors}",
            )

        # Check if too many errors
        if self._consecutive_errors >= self.config.max_consecutive_errors:
            await self._handle_too_many_errors()
        else:
            # Wait before retry
            await asyncio.sleep(self.config.retry_delay)

    async def _handle_too_many_errors(self) -> None:
        """Handle situation with too many consecutive errors."""
        pause_minutes = self.config.error_pause_duration

        logger.warning(
            f"Too many consecutive errors ({self._consecutive_errors}). "
            f"Pausing for {pause_minutes} minutes..."
        )

        if self._telegram:
            await self._telegram.notify_error(
                f"Too many errors ({self._consecutive_errors})",
                f"Pausing for {pause_minutes} minutes. Will restart automatically.",
            )

        # Reset session
        try:
            await self._navigator.reset_session()
        except Exception as e:
            logger.error(f"Failed to reset session: {e}")

        # Pause
        await asyncio.sleep(pause_minutes * 60)

        # Reset error counter
        self._consecutive_errors = 0

    def _get_next_interval(self) -> int:
        """Get next check interval in seconds."""
        if self.config.randomize_interval:
            return random.randint(
                self.config.min_interval,
                self.config.max_interval,
            )
        return self.config.min_interval

    def _is_within_active_hours(self) -> bool:
        """Check if current time is within active hours."""
        active_hours = self.config.get("schedule.active_hours")
        if not active_hours:
            return True

        start_str = active_hours.get("start")
        end_str = active_hours.get("end")

        if not start_str or not end_str:
            return True

        try:
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
            now = datetime.now().time()

            if start_time <= end_time:
                return start_time <= now <= end_time
            else:
                # Handles overnight ranges (e.g., 22:00 - 06:00)
                return now >= start_time or now <= end_time

        except ValueError:
            return True

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self._shutdown_requested = True

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def stop(self) -> None:
        """Stop the bot gracefully."""
        logger.info("Stopping bot...")
        self._shutdown_requested = True
        self._running = False

        # Send stop notification
        if self._telegram:
            await self._telegram.notify_stopped("Manual stop requested")

    async def _cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up...")

        # Close browser
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.error(f"Error closing browser: {e}")

        # Log final stats
        if self._start_time:
            runtime = datetime.now() - self._start_time
            logger.info("=" * 50)
            logger.info("Bot Statistics:")
            logger.info(f"  Runtime: {runtime}")
            logger.info(f"  Total checks: {self._checks_count}")
            logger.info(f"  Total errors: {self._errors_count}")
            logger.info(f"  Slots found: {self._slots_found_count}")
            logger.info("=" * 50)

        logger.info("Bot stopped")

    def get_stats(self) -> dict:
        """Get current bot statistics."""
        return {
            "running": self._running,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "checks_count": self._checks_count,
            "errors_count": self._errors_count,
            "consecutive_errors": self._consecutive_errors,
            "slots_found": self._slots_found_count,
            "last_check": self._last_check_time.isoformat() if self._last_check_time else None,
        }
