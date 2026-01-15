#!/usr/bin/env python3
"""
VFS Visa Slot Checker Bot - Entry Point

Usage:
    python -m src.main
    python -m src.main --config /path/to/config.yaml
    python -m src.main --test-telegram
    python -m src.main --debug
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.bot import VisaSlotBot
from src.utils.config import Config
from src.utils.logger import setup_logger, BotLogger
from src.notifications import TelegramNotifier


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="VFS Global Visa Slot Checker Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run with default config
    python -m src.main

    # Run with custom config
    python -m src.main --config /path/to/config.yaml

    # Test Telegram connection
    python -m src.main --test-telegram

    # Run in debug mode
    python -m src.main --debug
        """,
    )

    parser.add_argument(
        "--config", "-c",
        type=str,
        help="Path to configuration file (default: config/config.yaml)",
    )

    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Run in debug mode (verbose logging)",
    )

    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Test Telegram connection and exit",
    )

    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Test email connection and exit",
    )

    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate configuration and exit",
    )

    parser.add_argument(
        "--single-check",
        action="store_true",
        help="Run a single check and exit",
    )

    return parser.parse_args()


async def test_telegram(config: Config) -> bool:
    """Test Telegram connection."""
    logger = BotLogger("Test")

    if not config.telegram_enabled:
        logger.error("Telegram notifications are disabled in config")
        return False

    if not config.telegram_bot_token or not config.telegram_chat_id:
        logger.error("Telegram bot token or chat ID not configured")
        return False

    logger.info("Testing Telegram connection...")

    notifier = TelegramNotifier(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        enabled=True,
    )

    result = await notifier.test_connection()

    if result:
        logger.success("Telegram connection successful!")
    else:
        logger.error("Telegram connection failed")

    return result


async def test_email(config: Config) -> bool:
    """Test email connection."""
    from src.notifications import EmailNotifier

    logger = BotLogger("Test")

    if not config.email_enabled:
        logger.error("Email notifications are disabled in config")
        return False

    logger.info("Testing email connection...")

    notifier = EmailNotifier.from_config({
        **config.email_config,
        "enabled": True,
    })

    result = await notifier.test_connection()

    if result:
        logger.success("Email connection successful!")
    else:
        logger.error("Email connection failed")

    return result


def validate_config(config: Config) -> bool:
    """Validate configuration."""
    logger = BotLogger("Validate")

    logger.info("Validating configuration...")

    errors = config.validate()

    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        return False

    logger.success("Configuration is valid!")

    # Print summary
    print("\nConfiguration Summary:")
    print(f"  Mode: {config.mode}")
    print(f"  Country: {config.country_code} -> {config.destination_country}")
    print(f"  Visa type: {config.visa_type}")
    print(f"  Centers: {', '.join(config.centers)}")
    print(f"  Check interval: {config.min_interval}-{config.max_interval}s")
    print(f"  Browser: {config.browser_type} ({'headless' if config.browser_headless else 'headful'})")
    print(f"  Stealth mode: {config.stealth_mode}")
    print(f"  Telegram: {'enabled' if config.telegram_enabled else 'disabled'}")
    print(f"  Email: {'enabled' if config.email_enabled else 'disabled'}")
    print(f"  CAPTCHA auto-solve: {'enabled' if config.captcha_auto_solve else 'disabled'}")

    return True


async def run_single_check(config: Config) -> None:
    """Run a single check and exit."""
    logger = BotLogger("SingleCheck")
    logger.info("Running single check...")

    bot = VisaSlotBot(config)

    try:
        # Initialize components manually for single check
        await bot._initialize_components()
        await bot._browser.start()

        bot._navigator = bot.__class__.__bases__[0]  # This won't work, need proper init
        # For single check, we need to properly initialize

        from src.vfs_navigator import VFSNavigator
        from src.captcha import CaptchaSolver

        captcha_solver = CaptchaSolver(
            auto_solve=config.captcha_auto_solve,
            api_key=config.captcha_api_key,
        )

        navigator = VFSNavigator(
            browser_manager=bot._browser,
            config=config,
            captcha_solver=captcha_solver,
        )

        for center in config.centers:
            logger.info(f"Checking: {center}")
            result = await navigator.check_slots_for_center(center)
            logger.info(f"Result: {result.state.value}")

            if result.slots:
                for slot in result.slots:
                    print(f"\n🎉 SLOT FOUND!")
                    print(f"   Center: {slot.center}")
                    print(f"   Date: {slot.date}")
                    print(f"   Times: {', '.join(slot.time_slots)}")
                    print(f"   URL: {slot.booking_url}")

    finally:
        if bot._browser:
            await bot._browser.close()

    logger.info("Single check completed")


async def main():
    """Main entry point."""
    args = parse_args()

    # Set up basic logging
    log_level = "DEBUG" if args.debug else "INFO"
    setup_logger(level=log_level)

    logger = BotLogger("Main")

    try:
        # Load configuration
        config = Config(args.config)

        # Override debug mode if specified
        if args.debug:
            config._config["mode"] = "debug"
            config._config["logging"]["level"] = "DEBUG"

        # Handle test/validate commands
        if args.validate_config:
            success = validate_config(config)
            sys.exit(0 if success else 1)

        if args.test_telegram:
            success = await test_telegram(config)
            sys.exit(0 if success else 1)

        if args.test_email:
            success = await test_email(config)
            sys.exit(0 if success else 1)

        if args.single_check:
            await run_single_check(config)
            sys.exit(0)

        # Run the bot
        bot = VisaSlotBot(config)
        await bot.start()

    except FileNotFoundError as e:
        logger.error(str(e))
        logger.info("Please copy config/config.yaml.example to config/config.yaml")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error", e)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
