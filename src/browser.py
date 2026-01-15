"""
Browser management module.

Handles browser lifecycle, context management, and stealth configuration.
"""

import asyncio
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

from .antibot import StealthHelper, HumanBehavior
from .utils.config import Config
from .utils.logger import BotLogger

logger = BotLogger("Browser")


class BrowserManager:
    """
    Manages browser instance and provides stealth capabilities.
    """

    def __init__(self, config: Config):
        """
        Initialize browser manager.

        Args:
            config: Configuration instance
        """
        self.config = config
        self.stealth_helper = StealthHelper(rotate_user_agent=config.get("antibot.rotate_user_agent", True))
        self.human_behavior = HumanBehavior(
            typing_delay=config.typing_delay,
            action_delay=config.action_delay,
        )

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        # Session storage path for cookies persistence
        self._storage_path = Path(__file__).parent.parent / "data" / "session_storage.json"
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

    async def start(self) -> "Page":
        """
        Start browser and return page instance.

        Returns:
            Playwright Page instance
        """
        logger.info("Starting browser...")

        self._playwright = await async_playwright().start()

        # Check if we should connect to existing Chrome (recommended for VFS)
        cdp_url = self.config.get("browser.cdp_url", "")
        if cdp_url:
            return await self._connect_to_chrome(cdp_url)

        # Select browser type
        browser_type = self.config.browser_type
        if browser_type == "chromium":
            browser_launcher = self._playwright.chromium
        elif browser_type == "firefox":
            browser_launcher = self._playwright.firefox
        elif browser_type == "webkit":
            browser_launcher = self._playwright.webkit
        else:
            browser_launcher = self._playwright.chromium

        # Prepare launch options
        launch_options = {
            "headless": self.config.browser_headless,
            "slow_mo": self.config.browser_slow_mo,
        }

        # Add stealth args for Chromium
        if browser_type == "chromium" and self.config.stealth_mode:
            launch_options["args"] = self.stealth_helper.get_browser_args()

        # Add proxy if configured
        if self.config.proxy_enabled:
            proxy_config = self.config.proxy_config
            if proxy_config and proxy_config.get("server"):
                launch_options["proxy"] = {
                    "server": proxy_config["server"],
                }
                if proxy_config.get("username"):
                    launch_options["proxy"]["username"] = proxy_config["username"]
                    launch_options["proxy"]["password"] = proxy_config.get("password", "")

        # Launch browser
        self._browser = await browser_launcher.launch(**launch_options)
        logger.info(f"Browser launched: {browser_type}")

        # Create context
        await self._create_context()

        # Create page
        self._page = await self._context.new_page()

        # Apply stealth measures
        if self.config.stealth_mode:
            await self._apply_stealth()

        logger.info("Browser ready")
        return self._page

    async def _connect_to_chrome(self, cdp_url: str) -> "Page":
        """
        Connect to existing Chrome browser via CDP.

        This is the recommended way to bypass VFS anti-bot detection.
        Start Chrome with: google-chrome --remote-debugging-port=9222

        Args:
            cdp_url: CDP endpoint URL (e.g., http://localhost:9222)

        Returns:
            Page instance from connected browser
        """
        logger.info(f"Connecting to Chrome via CDP: {cdp_url}")

        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
            logger.info("Connected to Chrome successfully")

            # Get existing context
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                logger.info("Using existing browser context")
            else:
                raise Exception("No browser context found. Please open a tab first.")

            # Use EXISTING page - don't create new one!
            pages = self._context.pages
            if pages:
                # Use the last opened page (most likely the one user is working with)
                self._page = pages[-1]
                logger.info(f"Using existing tab: {self._page.url}")
            else:
                raise Exception("No tabs found. Please open VFS page first.")

            logger.info("Browser ready (connected to existing Chrome)")
            return self._page

        except Exception as e:
            logger.error(f"Failed to connect to Chrome: {e}")
            logger.error("Make sure Chrome is running with: --remote-debugging-port=9222")
            raise

    async def _create_context(self) -> None:
        """Create browser context with stealth options."""
        context_options = {}

        if self.config.stealth_mode:
            context_options = self.stealth_helper.get_context_options()
        else:
            context_options = {
                "viewport": self.config.viewport,
                "locale": "en-US",
            }

        # Try to load saved storage state
        if self._storage_path.exists():
            try:
                context_options["storage_state"] = str(self._storage_path)
                logger.debug("Loaded saved session storage")
            except Exception as e:
                logger.warning(f"Failed to load session storage: {e}")

        self._context = await self._browser.new_context(**context_options)

        # Set default timeouts
        self._context.set_default_timeout(30000)
        self._context.set_default_navigation_timeout(60000)

    async def _apply_stealth(self) -> None:
        """Apply stealth measures to page."""
        if not self._page:
            return

        # Apply playwright-stealth if available
        if STEALTH_AVAILABLE:
            await stealth_async(self._page)
            logger.debug("playwright-stealth applied")

        # Apply custom stealth scripts
        await self.stealth_helper.apply_stealth_scripts(self._page)

    async def save_session(self) -> None:
        """Save current session storage for persistence."""
        if self._context:
            try:
                await self._context.storage_state(path=str(self._storage_path))
                logger.debug("Session storage saved")
            except Exception as e:
                logger.warning(f"Failed to save session storage: {e}")

    async def close(self) -> None:
        """Close browser and cleanup."""
        logger.info("Closing browser...")

        # Save session before closing
        await self.save_session()

        if self._page:
            await self._page.close()
            self._page = None

        if self._context:
            await self._context.close()
            self._context = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("Browser closed")

    async def restart(self) -> "Page":
        """
        Restart browser with fresh context.

        Returns:
            New Page instance
        """
        logger.info("Restarting browser...")
        await self.close()
        await asyncio.sleep(2)  # Brief pause before restart
        return await self.start()

    @property
    def page(self) -> Optional[Page]:
        """Get current page instance."""
        return self._page

    @property
    def context(self) -> Optional[BrowserContext]:
        """Get current context instance."""
        return self._context

    @property
    def is_running(self) -> bool:
        """Check if browser is running."""
        return self._browser is not None and self._page is not None

    async def screenshot(self, path: str) -> None:
        """
        Take screenshot of current page.

        Args:
            path: Path to save screenshot
        """
        if self._page:
            await self._page.screenshot(path=path)
            logger.debug(f"Screenshot saved: {path}")

    async def handle_dialog(self, dialog) -> None:
        """
        Handle browser dialogs (alerts, confirms, prompts).

        Args:
            dialog: Dialog instance
        """
        logger.debug(f"Dialog appeared: {dialog.message}")
        await dialog.accept()

    def setup_dialog_handler(self) -> None:
        """Set up automatic dialog handling."""
        if self._page:
            self._page.on("dialog", self.handle_dialog)

    async def wait_for_load(self, timeout: int = 30000) -> None:
        """
        Wait for page to fully load.

        Args:
            timeout: Maximum wait time in milliseconds
        """
        if self._page:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)

    async def clear_cookies(self) -> None:
        """Clear all cookies from context."""
        if self._context:
            await self._context.clear_cookies()
            logger.debug("Cookies cleared")

    async def navigate(self, url: str, wait_until: str = "networkidle") -> None:
        """
        Navigate to URL with human-like behavior.

        Args:
            url: URL to navigate to
            wait_until: Wait condition (load, domcontentloaded, networkidle)
        """
        if not self._page:
            raise RuntimeError("Browser not started")

        logger.debug(f"Navigating to: {url}")

        # Random delay before navigation (human-like)
        if self.config.stealth_mode:
            await self.human_behavior.random_delay(0.5, 1.5)

        await self._page.goto(url, wait_until=wait_until)

        # Random delay after navigation
        if self.config.stealth_mode:
            await self.human_behavior.random_delay(1, 2)

    async def human_click(self, selector: str) -> None:
        """
        Click element with human-like behavior.

        Args:
            selector: Element selector
        """
        if not self._page:
            raise RuntimeError("Browser not started")

        await self.human_behavior.human_click(self._page, selector)

    async def human_type(self, selector: str, text: str) -> None:
        """
        Type text with human-like delays.

        Args:
            selector: Element selector
            text: Text to type
        """
        if not self._page:
            raise RuntimeError("Browser not started")

        await self.human_behavior.human_type(self._page, selector, text)

    async def random_activity(self) -> None:
        """Perform random human-like activity on page."""
        if not self._page or not self.config.stealth_mode:
            return

        # Random mouse movements
        if self.config.mouse_movements:
            await self.human_behavior.random_mouse_movement(self._page)

        # Random scrolling
        if self.config.random_scroll:
            await self.human_behavior.random_scroll(self._page)
