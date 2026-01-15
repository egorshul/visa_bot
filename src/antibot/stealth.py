"""
Stealth and human-like behavior module.

Provides functionality to make browser automation less detectable.
"""

import asyncio
import random
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from playwright.async_api import Page, Locator

from ..utils.logger import BotLogger

logger = BotLogger("Stealth")


class HumanBehavior:
    """
    Simulates human-like behavior in browser.
    """

    def __init__(
        self,
        typing_delay: Dict[str, int] = None,
        action_delay: Dict[str, int] = None,
    ):
        """
        Initialize human behavior simulator.

        Args:
            typing_delay: Dict with 'min' and 'max' typing delay in ms
            action_delay: Dict with 'min' and 'max' action delay in ms
        """
        self.typing_delay = typing_delay or {"min": 50, "max": 150}
        self.action_delay = action_delay or {"min": 500, "max": 2000}

    def get_typing_delay(self) -> int:
        """Get random typing delay in milliseconds."""
        return random.randint(self.typing_delay["min"], self.typing_delay["max"])

    def get_action_delay(self) -> float:
        """Get random action delay in seconds."""
        delay_ms = random.randint(self.action_delay["min"], self.action_delay["max"])
        return delay_ms / 1000

    async def random_delay(self, min_sec: float = 0.5, max_sec: float = 2.0) -> None:
        """
        Wait for a random amount of time.

        Args:
            min_sec: Minimum delay in seconds
            max_sec: Maximum delay in seconds
        """
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def human_type(self, page: "Page", selector: str, text: str) -> None:
        """
        Type text with human-like delays.

        Args:
            page: Playwright page instance
            selector: Element selector
            text: Text to type
        """
        element = page.locator(selector)
        await element.click()
        await self.random_delay(0.1, 0.3)

        for char in text:
            await element.type(char, delay=self.get_typing_delay())
            # Occasionally pause like a human thinking
            if random.random() < 0.1:
                await self.random_delay(0.2, 0.5)

    async def human_click(self, page: "Page", selector: str) -> None:
        """
        Click element with human-like behavior.

        Args:
            page: Playwright page instance
            selector: Element selector
        """
        element = page.locator(selector)

        # Wait for element to be visible
        await element.wait_for(state="visible", timeout=10000)

        # Get element bounding box
        box = await element.bounding_box()
        if box:
            # Click at random position within element
            x = box["x"] + random.uniform(5, box["width"] - 5)
            y = box["y"] + random.uniform(5, box["height"] - 5)
            await page.mouse.click(x, y)
        else:
            await element.click()

        await self.random_delay(0.1, 0.3)

    async def random_mouse_movement(self, page: "Page") -> None:
        """
        Perform random mouse movement.

        Args:
            page: Playwright page instance
        """
        viewport = page.viewport_size
        if not viewport:
            return

        # Generate random points for mouse movement
        num_points = random.randint(2, 5)
        for _ in range(num_points):
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)

            # Move mouse with human-like curve
            await self._bezier_mouse_move(page, x, y)
            await self.random_delay(0.05, 0.2)

    async def _bezier_mouse_move(
        self, page: "Page", target_x: int, target_y: int, steps: int = 20
    ) -> None:
        """
        Move mouse along a bezier curve (more human-like).

        Args:
            page: Playwright page instance
            target_x: Target X coordinate
            target_y: Target Y coordinate
            steps: Number of steps in the movement
        """
        # Get current mouse position (approximate from viewport center)
        viewport = page.viewport_size
        if not viewport:
            return

        start_x = viewport["width"] // 2
        start_y = viewport["height"] // 2

        # Generate control points for bezier curve
        cp1_x = start_x + random.randint(-100, 100)
        cp1_y = start_y + random.randint(-100, 100)
        cp2_x = target_x + random.randint(-100, 100)
        cp2_y = target_y + random.randint(-100, 100)

        # Generate points along bezier curve
        for i in range(steps):
            t = i / steps
            # Cubic bezier formula
            x = (
                (1 - t) ** 3 * start_x
                + 3 * (1 - t) ** 2 * t * cp1_x
                + 3 * (1 - t) * t**2 * cp2_x
                + t**3 * target_x
            )
            y = (
                (1 - t) ** 3 * start_y
                + 3 * (1 - t) ** 2 * t * cp1_y
                + 3 * (1 - t) * t**2 * cp2_y
                + t**3 * target_y
            )

            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.001, 0.01))

    async def random_scroll(self, page: "Page") -> None:
        """
        Perform random scrolling behavior.

        Args:
            page: Playwright page instance
        """
        scroll_actions = random.randint(1, 3)

        for _ in range(scroll_actions):
            # Random scroll direction and amount
            direction = random.choice(["up", "down"])
            amount = random.randint(100, 400)

            if direction == "up":
                amount = -amount

            await page.mouse.wheel(0, amount)
            await self.random_delay(0.3, 0.8)

    async def simulate_reading(self, page: "Page", min_sec: float = 1, max_sec: float = 3) -> None:
        """
        Simulate user reading the page.

        Args:
            page: Playwright page instance
            min_sec: Minimum reading time
            max_sec: Maximum reading time
        """
        # Small random mouse movements while "reading"
        num_movements = random.randint(1, 3)
        total_time = random.uniform(min_sec, max_sec)
        time_per_movement = total_time / num_movements

        for _ in range(num_movements):
            await self.random_mouse_movement(page)
            await asyncio.sleep(time_per_movement)


class StealthHelper:
    """
    Helper class for applying stealth techniques to browser.
    """

    # Common user agents for rotation
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]

    # Common screen resolutions
    RESOLUTIONS = [
        {"width": 1920, "height": 1080},
        {"width": 1366, "height": 768},
        {"width": 1536, "height": 864},
        {"width": 1440, "height": 900},
        {"width": 1280, "height": 720},
    ]

    # Common timezones
    TIMEZONES = [
        "Europe/Moscow",
        "Europe/London",
        "Europe/Paris",
        "America/New_York",
    ]

    def __init__(self, rotate_user_agent: bool = True):
        """
        Initialize stealth helper.

        Args:
            rotate_user_agent: Whether to rotate user agents
        """
        self.rotate_user_agent = rotate_user_agent
        self._current_user_agent: Optional[str] = None

    def get_random_user_agent(self) -> str:
        """Get a random user agent string."""
        if self.rotate_user_agent:
            self._current_user_agent = random.choice(self.USER_AGENTS)
        elif self._current_user_agent is None:
            self._current_user_agent = self.USER_AGENTS[0]

        return self._current_user_agent

    def get_random_viewport(self) -> Dict[str, int]:
        """Get a random viewport size."""
        return random.choice(self.RESOLUTIONS)

    def get_random_timezone(self) -> str:
        """Get a random timezone."""
        return random.choice(self.TIMEZONES)

    async def apply_stealth_scripts(self, page: "Page") -> None:
        """
        Apply stealth JavaScript to page.

        Args:
            page: Playwright page instance
        """
        # Override navigator.webdriver
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Override navigator.plugins
        await page.add_init_script("""
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
        """)

        # Override navigator.languages
        await page.add_init_script("""
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'ru']
            });
        """)

        # Override chrome detection
        await page.add_init_script("""
            window.chrome = {
                runtime: {}
            };
        """)

        # Override permissions
        await page.add_init_script("""
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
        """)

        logger.debug("Stealth scripts applied to page")

    def get_browser_args(self) -> List[str]:
        """
        Get browser launch arguments for stealth.

        Returns:
            List of browser arguments
        """
        return [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-breakpad",
            "--disable-component-extensions-with-background-pages",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-features=TranslateUI",
            "--disable-hang-monitor",
            "--disable-ipc-flooding-protection",
            "--disable-popup-blocking",
            "--disable-prompt-on-repost",
            "--disable-renderer-backgrounding",
            "--disable-sync",
            "--enable-features=NetworkService,NetworkServiceInProcess",
            "--force-color-profile=srgb",
            "--metrics-recording-only",
            "--no-first-run",
            "--password-store=basic",
            "--use-mock-keychain",
            "--window-size=1920,1080",
        ]

    def get_context_options(self) -> Dict:
        """
        Get browser context options for stealth.

        Returns:
            Dictionary of context options
        """
        viewport = self.get_random_viewport()

        return {
            "user_agent": self.get_random_user_agent(),
            "viewport": viewport,
            "screen": viewport,
            "timezone_id": "Europe/Moscow",
            "locale": "en-US",
            "color_scheme": "light",
            "java_script_enabled": True,
            "has_touch": False,
            "is_mobile": False,
            "device_scale_factor": 1,
        }
