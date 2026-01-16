"""
VFS Global website navigation module.

Handles login, navigation, and slot availability checking.
"""

import asyncio
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from playwright.async_api import Page, Locator

from .browser import BrowserManager
from .captcha import CaptchaSolver
from .utils.config import Config
from .utils.logger import BotLogger

logger = BotLogger("VFS")


# =============================================================================
# HUMAN BEHAVIOR SIMULATION - Anti-detection techniques
# =============================================================================

class HumanBehavior:
    """
    Simulates human-like behavior to avoid bot detection.
    All techniques based on real human interaction patterns.
    """

    def __init__(self, page: "Page"):
        self.page = page
        self._last_action_time = datetime.now()

    # -------------------------------------------------------------------------
    # 1. GAUSSIAN JITTER - More realistic than uniform random
    # -------------------------------------------------------------------------
    @staticmethod
    def gaussian_delay(base: float, std_dev: float = 0.3) -> float:
        """
        Generate delay with gaussian distribution (more human-like).
        Most values cluster around base, occasionally slower/faster.
        """
        delay = random.gauss(base, base * std_dev)
        return max(0.1, delay)  # Never negative or too fast

    @staticmethod
    def gaussian_range(min_val: float, max_val: float) -> float:
        """Gaussian distributed value between min and max."""
        mean = (min_val + max_val) / 2
        std_dev = (max_val - min_val) / 4  # 95% within range
        value = random.gauss(mean, std_dev)
        return max(min_val, min(max_val, value))

    # -------------------------------------------------------------------------
    # 2. TIME-OF-DAY SPEED VARIATION
    # -------------------------------------------------------------------------
    @staticmethod
    def get_time_multiplier() -> float:
        """
        People are faster in morning, slower in evening.
        Returns multiplier for delays (1.0 = normal).
        """
        hour = datetime.now().hour

        if 6 <= hour < 9:      # Early morning - still waking up
            return 1.3
        elif 9 <= hour < 12:   # Morning - most alert
            return 0.8
        elif 12 <= hour < 14:  # Lunch - slower
            return 1.2
        elif 14 <= hour < 17:  # Afternoon - normal
            return 1.0
        elif 17 <= hour < 20:  # Evening - getting tired
            return 1.2
        elif 20 <= hour < 23:  # Night - tired
            return 1.4
        else:                   # Late night - very slow
            return 1.6

    async def human_delay(self, base_seconds: float) -> None:
        """Wait with human-like variation based on time of day."""
        multiplier = self.get_time_multiplier()
        actual_delay = self.gaussian_delay(base_seconds * multiplier)
        await asyncio.sleep(actual_delay)

    # -------------------------------------------------------------------------
    # 3. MOUSE MOVEMENTS - Bezier curves like real mouse
    # -------------------------------------------------------------------------
    async def move_mouse_to_element(self, element: "Locator") -> None:
        """
        Move mouse to element with human-like curve.
        Uses bezier curve, not straight line.
        """
        try:
            box = await element.bounding_box()
            if not box:
                return

            # Target point with slight randomness (don't always hit center)
            target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

            # Get current mouse position (approximate from viewport center)
            viewport = self.page.viewport_size
            if viewport:
                start_x = viewport["width"] / 2
                start_y = viewport["height"] / 2
            else:
                start_x, start_y = 500, 400

            # Generate bezier curve points
            points = self._bezier_curve(start_x, start_y, target_x, target_y)

            # Move through points with varying speed
            for i, (x, y) in enumerate(points):
                # Slow down near the end (like real mouse)
                if i > len(points) * 0.7:
                    delay = random.uniform(0.01, 0.03)
                else:
                    delay = random.uniform(0.005, 0.015)

                await self.page.mouse.move(x, y)
                await asyncio.sleep(delay)

        except Exception as e:
            # Silently fail - mouse movement is optional
            pass

    def _bezier_curve(self, x1: float, y1: float, x2: float, y2: float, steps: int = 20) -> list:
        """Generate points along a bezier curve between two points."""
        points = []

        # Random control points for natural curve
        ctrl1_x = x1 + (x2 - x1) * random.uniform(0.2, 0.4) + random.uniform(-50, 50)
        ctrl1_y = y1 + (y2 - y1) * random.uniform(0.2, 0.4) + random.uniform(-50, 50)
        ctrl2_x = x1 + (x2 - x1) * random.uniform(0.6, 0.8) + random.uniform(-30, 30)
        ctrl2_y = y1 + (y2 - y1) * random.uniform(0.6, 0.8) + random.uniform(-30, 30)

        for i in range(steps + 1):
            t = i / steps
            # Cubic bezier formula
            x = (1-t)**3 * x1 + 3*(1-t)**2*t * ctrl1_x + 3*(1-t)*t**2 * ctrl2_x + t**3 * x2
            y = (1-t)**3 * y1 + 3*(1-t)**2*t * ctrl1_y + 3*(1-t)*t**2 * ctrl2_y + t**3 * y2
            points.append((x, y))

        return points

    # -------------------------------------------------------------------------
    # 4. RANDOM SCROLLING - People scroll around
    # -------------------------------------------------------------------------
    async def random_scroll(self) -> None:
        """Perform random scroll like human browsing."""
        direction = random.choice(["up", "down", "none"])

        if direction == "none":
            return

        scroll_amount = random.randint(50, 200)
        if direction == "up":
            scroll_amount = -scroll_amount

        await self.page.mouse.wheel(0, scroll_amount)
        await asyncio.sleep(self.gaussian_delay(0.3))

        # Sometimes scroll back a bit
        if random.random() < 0.3:
            await self.page.mouse.wheel(0, -scroll_amount // 2)
            await asyncio.sleep(self.gaussian_delay(0.2))

    async def scroll_element_into_view(self, element: "Locator") -> None:
        """Scroll to element with human-like behavior."""
        try:
            # First a random small scroll
            if random.random() < 0.4:
                await self.random_scroll()

            # Then scroll to element
            await element.scroll_into_view_if_needed()
            await asyncio.sleep(self.gaussian_delay(0.3))

        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 5. HUMAN MISTAKES - Occasionally make "errors"
    # -------------------------------------------------------------------------
    async def maybe_make_mistake(self, page: "Page", probability: float = 0.1) -> bool:
        """
        Sometimes humans misclick or open wrong thing.
        Returns True if mistake was made.
        """
        if random.random() > probability:
            return False

        mistake_type = random.choice(["wrong_dropdown", "hover_wrong", "scroll_away"])

        try:
            if mistake_type == "wrong_dropdown":
                # Click a dropdown and immediately close it
                dropdowns = await page.locator("mat-select").all()
                if len(dropdowns) > 1:
                    wrong_dropdown = random.choice(dropdowns)
                    await wrong_dropdown.click()
                    await asyncio.sleep(self.gaussian_delay(0.5))
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(self.gaussian_delay(0.3))
                    print("  [Human] Accidentally opened wrong dropdown, closing...")
                    return True

            elif mistake_type == "hover_wrong":
                # Hover over some random element
                buttons = await page.locator("button").all()
                if buttons:
                    random_btn = random.choice(buttons)
                    await self.move_mouse_to_element(random_btn)
                    await asyncio.sleep(self.gaussian_delay(0.3))
                    return True

            elif mistake_type == "scroll_away":
                # Scroll away and back
                await self.page.mouse.wheel(0, random.randint(100, 300))
                await asyncio.sleep(self.gaussian_delay(0.5))
                await self.page.mouse.wheel(0, random.randint(-300, -100))
                await asyncio.sleep(self.gaussian_delay(0.3))
                print("  [Human] Scrolled away and back...")
                return True

        except Exception:
            pass

        return False

    # -------------------------------------------------------------------------
    # 6. RANDOM LONG PAUSES - Coffee breaks, phone calls, etc
    # -------------------------------------------------------------------------
    @staticmethod
    def should_take_break(cycle_count: int) -> Tuple[bool, int]:
        """
        Decide if should take a long break.
        Returns (should_break, break_duration_seconds).
        """
        # Every 5-10 cycles, maybe take a break
        if cycle_count > 0 and cycle_count % random.randint(5, 10) == 0:
            if random.random() < 0.3:  # 30% chance
                # Break duration: 5-15 minutes
                duration = random.randint(300, 900)
                return True, duration

        # Very rare: long break (like went to lunch)
        if random.random() < 0.02:  # 2% chance
            duration = random.randint(600, 1200)  # 10-20 min
            return True, duration

        return False, 0

    async def take_break(self, duration: int, reason: str = "Taking a break") -> None:
        """Take a human-like break."""
        print(f"\n  ☕ {reason} ({duration // 60} min {duration % 60} sec)...")
        logger.info(f"Taking break: {duration}s - {reason}")

        # During break, maybe move mouse occasionally
        chunks = duration // 30  # Check every 30 seconds
        for i in range(chunks):
            await asyncio.sleep(30)

            # Occasionally move mouse slightly (not AFK)
            if random.random() < 0.2:
                try:
                    viewport = self.page.viewport_size
                    if viewport:
                        x = viewport["width"] / 2 + random.randint(-100, 100)
                        y = viewport["height"] / 2 + random.randint(-100, 100)
                        await self.page.mouse.move(x, y)
                except Exception:
                    pass

        # Remaining time
        remaining = duration % 30
        if remaining > 0:
            await asyncio.sleep(remaining)

        print(f"  ☕ Break finished, resuming...")

    # -------------------------------------------------------------------------
    # 7. BLOCK DETECTION - Stop if detected
    # -------------------------------------------------------------------------
    async def check_if_blocked(self, page: "Page") -> Tuple[bool, str]:
        """
        Check if we got blocked by VFS.
        Returns (is_blocked, reason).
        """
        try:
            page_text = await page.content()
            page_lower = page_text.lower()

            # Check for block indicators
            block_indicators = [
                ("access restricted", "Access Restricted"),
                ("access denied", "Access Denied"),
                ("blocked", "Blocked"),
                ("unusual activity", "Unusual Activity Detected"),
                ("too many requests", "Too Many Requests"),
                ("rate limit", "Rate Limited"),
                ("temporarily banned", "Temporarily Banned"),
                ("your ip has been", "IP Blocked"),
                ("user id (429", "User ID Blocked (429)"),
            ]

            for indicator, reason in block_indicators:
                if indicator in page_lower:
                    return True, reason

            # Check for error codes in URL
            url = page.url.lower()
            if "error" in url or "blocked" in url or "denied" in url:
                return True, "Error URL detected"

            return False, ""

        except Exception as e:
            return False, ""


class PageState(Enum):
    """Possible page states during navigation."""

    UNKNOWN = "unknown"
    LOGIN_PAGE = "login_page"
    LOGGED_IN = "logged_in"
    APPLICATION_PAGE = "application_page"
    VISA_TYPE_SELECTION = "visa_type_selection"
    CENTER_SELECTION = "center_selection"
    CALENDAR_PAGE = "calendar_page"
    SLOT_SELECTION = "slot_selection"
    NO_SLOTS = "no_slots"
    QUEUE = "queue"
    BLOCKED = "blocked"
    ERROR = "error"
    CAPTCHA = "captcha"


@dataclass
class SlotInfo:
    """Information about available slot."""

    center: str
    date: str
    time_slots: List[str] = field(default_factory=list)
    booking_url: str = ""


@dataclass
class CheckResult:
    """Result of slot check."""

    state: PageState
    slots: List[SlotInfo] = field(default_factory=list)
    error_message: str = ""
    needs_retry: bool = False


class VFSNavigator:
    """
    Navigates VFS Global website and checks for available slots.
    """

    # Common selectors for VFS website
    SELECTORS = {
        # Login - VFS uses Angular Material
        "email_input": "#email",
        "password_input": "#password",
        "login_button": "button[type='submit']",
        "login_form": "form",

        # Navigation
        "new_booking_btn": "button:has-text('New Booking'), a:has-text('New Booking'), .new-booking",
        "schedule_appointment": "a:has-text('Schedule Appointment'), button:has-text('Schedule')",

        # Visa type selection
        "visa_category": "mat-select[formcontrolname='VisaCategory'], #mat-select-0",
        "visa_subcategory": "mat-select[formcontrolname='VisaSubCategory'], #mat-select-2",
        "short_stay_option": "mat-option:has-text('Short Stay')",

        # Center selection
        "center_dropdown": "mat-select[formcontrolname='VisaCentre'], mat-select:has-text('Centre')",
        "center_option": "mat-option:has-text('{center}')",

        # Applicants
        "applicants_dropdown": "mat-select[formcontrolname='NumberOfApplicants']",

        # Continue/Submit buttons
        "continue_button": "button:has-text('Continue'), button:has-text('Submit')",
        "submit_button": "button[type='submit']",

        # Calendar and slots
        "calendar_container": ".calendar-container, .datepicker, #calendar, mat-calendar",
        "available_date": ".mat-calendar-body-cell:not(.mat-calendar-body-disabled)",
        "time_slot": ".time-slot:not(.disabled), .slot-available, .appointment-slot",
        "slot_time_text": ".slot-time, .time-text",

        # Messages
        "no_slots_message": ":has-text('No appointment'), :has-text('no slots'), :has-text('not available')",
        "queue_message": ":has-text('queue'), :has-text('Queue')",
        "error_message": ".error-message, .alert-danger, .error, mat-error",

        # General
        "loading_spinner": ".loading, .spinner, .loader, mat-spinner",
        "modal_close": ".modal-close, .close-modal, button[aria-label='Close']",
    }

    # VFS specific URL patterns
    URL_PATTERNS = {
        "login": r"/login",
        "dashboard": r"/dashboard|/home",
        "application": r"/application",
        "appointment": r"/appointment|/schedule",
        "calendar": r"/calendar|/date-selection",
    }

    def __init__(
        self,
        browser_manager: BrowserManager,
        config: Config,
        captcha_solver: Optional[CaptchaSolver] = None,
    ):
        """
        Initialize VFS navigator.

        Args:
            browser_manager: Browser manager instance
            config: Configuration instance
            captcha_solver: Optional CAPTCHA solver
        """
        self.browser = browser_manager
        self.config = config
        self.captcha_solver = captcha_solver
        self._logged_in = False
        self._current_state = PageState.UNKNOWN
        self._human: Optional[HumanBehavior] = None  # Lazy init after page ready
        self._is_blocked = False
        self._block_reason = ""

    def _get_human(self) -> HumanBehavior:
        """Get or create HumanBehavior instance."""
        if self._human is None:
            self._human = HumanBehavior(self.page)
        return self._human

    @property
    def page(self) -> "Page":
        """Get current page instance."""
        return self.browser.page

    async def _pass_cloudflare(self) -> bool:
        """
        Navigate to main page and wait for Cloudflare challenge to pass.

        Returns:
            True if passed successfully
        """
        logger.info("Passing Cloudflare protection...")

        # Go to main page first
        base_url = f"{self.config.vfs_base_url}/{self.config.country_code}/{self.config.language}/{self.config.destination_country}"
        await self.browser.navigate(base_url, wait_until="domcontentloaded")

        # Wait for Cloudflare challenge (up to 30 seconds)
        for i in range(15):
            await asyncio.sleep(2)

            # Check if still on challenge page
            page_content = await self.page.content()
            if "challenge" in page_content.lower() or "checking your browser" in page_content.lower():
                logger.debug(f"Waiting for Cloudflare... ({i+1}/15)")
                continue

            # Check if page loaded normally
            if await self._element_exists("body"):
                title = await self.page.title()
                if title and "just a moment" not in title.lower():
                    logger.info("Cloudflare passed successfully")
                    return True

        logger.warning("Cloudflare challenge may not have completed")
        return True  # Continue anyway

    async def login(self) -> bool:
        """
        Log in to VFS Global account.

        Returns:
            True if login successful
        """
        logger.info("Starting login process...")

        try:
            # Check if already logged in (e.g., when using existing Chrome session)
            current_url = self.page.url
            logger.debug(f"Current URL: {current_url}")

            if await self._is_logged_in():
                logger.info("Already logged in!")
                self._logged_in = True
                return True

            # If on dashboard or app page, we're already logged in
            if "dashboard" in current_url or "application" in current_url:
                logger.info("Already on dashboard/application page - logged in!")
                self._logged_in = True
                return True

            # Skip Cloudflare wait if already on VFS site (connected to existing Chrome)
            if "vfsglobal.com" not in current_url:
                await self._pass_cloudflare()
            else:
                logger.info("Already on VFS site, skipping Cloudflare check")

            # Now navigate to login page
            login_url = self.config.get_login_url()
            logger.debug(f"Navigating to: {login_url}")
            await self.browser.navigate(login_url, wait_until="domcontentloaded")

            # Wait for page to fully load
            await asyncio.sleep(3)
            await self.browser.wait_for_load()

            # Check for CAPTCHA
            if self.captcha_solver:
                captcha_solved = await self.captcha_solver.check_and_solve(self.page)
                if not captcha_solved:
                    logger.error("CAPTCHA detected and could not be solved")
                    self._current_state = PageState.CAPTCHA
                    return False

            # Wait for login form
            await self._wait_for_element(self.SELECTORS["email_input"])

            # Enter credentials
            logger.debug("Entering email...")
            await self.browser.human_type(
                self.SELECTORS["email_input"],
                self.config.vfs_email,
            )

            await self.browser.human_behavior.random_delay(0.5, 1)

            logger.debug("Entering password...")
            await self.browser.human_type(
                self.SELECTORS["password_input"],
                self.config.vfs_password,
            )

            await self.browser.human_behavior.random_delay(0.5, 1)

            # Click login button - try multiple selectors
            logger.debug("Looking for login button...")
            login_btn_selectors = [
                "button:has-text('Sign In')",
                "button:has-text('Login')",
                "button:has-text('SIGN IN')",
                "button[type='submit']",
                ".mat-button:has-text('Sign')",
                "button.mat-raised-button",
            ]

            clicked = False
            for selector in login_btn_selectors:
                try:
                    if await self._element_exists(selector):
                        logger.debug(f"Found login button: {selector}")
                        await self.browser.human_click(selector)
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                # Take screenshot for debugging
                logger.error("Login button not found! Taking screenshot...")
                await self.take_screenshot("login_error")
                logger.error(f"Current URL: {self.page.url}")
                raise Exception("Login button not found")

            # Wait for navigation
            await asyncio.sleep(3)
            await self.browser.wait_for_load()

            # Check if login successful
            if await self._is_logged_in():
                logger.info("Login successful")
                self._logged_in = True
                self._current_state = PageState.LOGGED_IN
                return True
            else:
                logger.error("Login failed - still on login page or error")
                self._current_state = PageState.ERROR
                return False

        except Exception as e:
            logger.exception("Login failed", e)
            self._current_state = PageState.ERROR
            return False

    async def _is_logged_in(self) -> bool:
        """Check if currently logged in."""
        url = self.page.url

        # Check URL patterns
        if re.search(self.URL_PATTERNS["login"], url):
            return False

        if re.search(self.URL_PATTERNS["dashboard"], url):
            return True

        # Check for dashboard elements
        dashboard_indicators = [
            ".user-profile",
            ".dashboard",
            "a:has-text('Logout')",
            "button:has-text('Logout')",
            ".welcome-message",
        ]

        for selector in dashboard_indicators:
            if await self._element_exists(selector):
                return True

        return False

    async def navigate_to_appointment(self) -> bool:
        """
        Check if already on appointment page. DON'T navigate - use current page.

        Returns:
            True if on appointment page
        """
        current_url = self.page.url
        print(f"DEBUG: Current page URL: {current_url}")

        # Check if we're on the right page
        if "application" in current_url:
            print("DEBUG: Already on application page - good!")
            self._current_state = PageState.APPLICATION_PAGE
            return True
        else:
            print(f"ERROR: NOT on application page!")
            print(f"Please navigate manually to: {self.config.get_application_url()}")
            return False

    async def _is_on_application_page(self) -> bool:
        """Check if on application/appointment page."""
        url = self.page.url
        return bool(
            re.search(self.URL_PATTERNS["application"], url) or
            re.search(self.URL_PATTERNS["appointment"], url)
        )

    async def _check_cloudflare_captcha(self) -> bool:
        """
        Check if Cloudflare CAPTCHA/challenge is present.

        Returns:
            True if Cloudflare challenge is detected
        """
        try:
            # Check page title
            title = await self.page.title()
            if title and "just a moment" in title.lower():
                return True

            # Check for Cloudflare elements
            cloudflare_indicators = [
                "#challenge-running",
                "#challenge-stage",
                ".cf-turnstile",
                "iframe[src*='challenges.cloudflare.com']",
                "#cf-challenge-running",
                "[data-ray]",  # Cloudflare ray ID
            ]

            for selector in cloudflare_indicators:
                try:
                    element = self.page.locator(selector)
                    if await element.count() > 0:
                        return True
                except:
                    pass

            # Check page content for Cloudflare text
            page_content = await self.page.content()
            cloudflare_texts = [
                "checking your browser",
                "please wait while we verify",
                "this process is automatic",
                "ray id:",
                "cloudflare",
                "please complete the security check",
            ]

            page_lower = page_content.lower()
            for text in cloudflare_texts:
                if text in page_lower and "vfsglobal" not in page_lower[:500]:
                    # Only trigger if we're not on the VFS page
                    return True

            return False

        except Exception as e:
            print(f"  DEBUG: Error checking Cloudflare: {e}")
            return False

    async def wait_for_cloudflare_to_pass(self, timeout_seconds: int = 120) -> bool:
        """
        Wait for Cloudflare challenge to be solved (automatically or manually).

        Args:
            timeout_seconds: Maximum time to wait for CAPTCHA to be solved

        Returns:
            True if challenge passed, False if timeout
        """
        print("\n" + "=" * 60)
        print("⚠️  CLOUDFLARE CAPTCHA DETECTED!")
        print("=" * 60)

        # Try automatic solving if captcha_solver is configured
        if self.captcha_solver and self.captcha_solver.auto_solve and self.captcha_solver.api_key:
            print("Attempting AUTOMATIC solving via 2Captcha/Anti-Captcha...")
            print("=" * 60 + "\n")

            try:
                solved = await self.captcha_solver.check_and_solve(self.page)
                if solved:
                    print("\n✅ Cloudflare CAPTCHA solved automatically!")
                    logger.info("Cloudflare CAPTCHA solved via auto-solver")
                    await asyncio.sleep(2)
                    return True
                else:
                    print("  Auto-solve returned False, falling back to manual...")
            except Exception as e:
                logger.error(f"Auto-solve failed: {e}")
                print(f"  Auto-solve failed: {e}")

        # Fallback to manual solving
        print("Please solve the CAPTCHA in the browser window.")
        print(f"Waiting up to {timeout_seconds} seconds...")
        print("=" * 60 + "\n")

        logger.warning("Cloudflare CAPTCHA - waiting for manual solve")

        start_time = datetime.now()
        check_interval = 2  # Check every 2 seconds

        while (datetime.now() - start_time).total_seconds() < timeout_seconds:
            # Check if Cloudflare challenge is still present
            if not await self._check_cloudflare_captcha():
                # Challenge passed!
                print("\n✅ Cloudflare CAPTCHA solved! Continuing...")
                logger.info("Cloudflare CAPTCHA solved")
                await asyncio.sleep(2)  # Small delay after solving
                return True

            # Still waiting
            elapsed = int((datetime.now() - start_time).total_seconds())
            if elapsed % 10 == 0:  # Print status every 10 seconds
                print(f"  Waiting for CAPTCHA... ({elapsed}s / {timeout_seconds}s)")

            await asyncio.sleep(check_interval)

        # Timeout
        print("\n❌ Timeout waiting for Cloudflare CAPTCHA!")
        logger.error("Timeout waiting for Cloudflare CAPTCHA")
        return False

    async def _select_dropdown_by_index(self, index: int, option_text: str, wait_for_load: bool = True) -> bool:
        """
        Select an option from mat-select dropdown by its index on the page.
        Uses human-like behavior for all interactions.

        Args:
            index: Index of the mat-select (0 = first, 1 = second, etc.)
            option_text: Text of the option to select
            wait_for_load: Whether to wait for loading after selection

        Returns:
            True if option selected successfully
        """
        human = self._get_human()

        try:
            # Wait for dropdowns to be present
            for attempt in range(20):
                mat_selects = await self.page.locator("mat-select").all()
                if len(mat_selects) > index:
                    break
                await asyncio.sleep(0.5)

            mat_selects = await self.page.locator("mat-select").all()

            if index >= len(mat_selects):
                print(f"  [!] Dropdown {index} not found (only {len(mat_selects)} exist)")
                return False

            dropdown = mat_selects[index]

            # HUMAN: Maybe scroll to see the dropdown
            await human.scroll_element_into_view(dropdown)

            # HUMAN: Move mouse to dropdown with bezier curve
            await human.move_mouse_to_element(dropdown)

            # HUMAN: Thinking delay (gaussian, time-of-day adjusted)
            await human.human_delay(1.0)

            # Click to open dropdown
            await dropdown.click()

            # HUMAN: Wait while "reading" options (gaussian delay)
            await asyncio.sleep(human.gaussian_delay(1.0))

            # Wait for options panel to appear
            try:
                await self.page.wait_for_selector("mat-option", timeout=5000)
            except:
                print(f"  [!] No options appeared for dropdown {index}")
                return False

            all_options = await self.page.locator("mat-option").all()

            # HUMAN: "Reading" the options (time varies by number of options)
            read_time = min(0.1 * len(all_options), 1.5)
            await asyncio.sleep(human.gaussian_delay(read_time))

            # Find and click the option containing our text
            option = self.page.locator(f"mat-option:has-text('{option_text}')").first
            if await option.count() > 0:
                # HUMAN: Move mouse to option
                await human.move_mouse_to_element(option)
                await asyncio.sleep(human.gaussian_delay(0.2))

                await option.click()
                print(f"  → Selected: {option_text}")

                # Wait for loading after selection
                if wait_for_load:
                    # HUMAN: Gaussian delay (2-4 seconds, time-adjusted)
                    await human.human_delay(3.0)

                    # Wait for any spinner to disappear
                    try:
                        spinner = self.page.locator("mat-spinner, .loading, .spinner")
                        if await spinner.count() > 0:
                            await spinner.wait_for(state="hidden", timeout=10000)
                    except:
                        pass

                return True

            print(f"  [!] Option '{option_text}' not found in dropdown {index}")

            # Close dropdown by pressing Escape
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            return False

        except Exception as e:
            print(f"  DEBUG: mat-select[{index}] Error: {e}")
            # Try to close any open dropdown
            try:
                await self.page.keyboard.press("Escape")
            except:
                pass
            return False

    async def _click_mat_select_option(self, dropdown_selector: str, option_texts: list) -> bool:
        """
        Click on Angular Material mat-select and choose an option.

        Args:
            dropdown_selector: Selector for the mat-select element
            option_texts: List of possible option texts to try

        Returns:
            True if option selected successfully
        """
        try:
            # Click to open dropdown
            dropdown = self.page.locator(dropdown_selector).first
            if await dropdown.count() == 0:
                print(f"  DEBUG: Dropdown not found: {dropdown_selector}")
                return False

            print(f"  DEBUG: Clicking dropdown: {dropdown_selector}")
            await dropdown.click()
            await asyncio.sleep(1)

            # Wait for options panel to appear
            try:
                await self.page.wait_for_selector("mat-option", timeout=5000)
            except:
                print("  DEBUG: No mat-option appeared after click")
                return False

            # DEBUG: List all available options
            all_options = await self.page.locator("mat-option").all()
            print(f"  DEBUG: Available options ({len(all_options)}):")
            for opt in all_options:
                try:
                    opt_text = await opt.text_content()
                    print(f"    - '{opt_text}'")
                except:
                    pass

            # Try each option text
            for text in option_texts:
                option = self.page.locator(f"mat-option:has-text('{text}')").first
                if await option.count() > 0:
                    await option.click()
                    print(f"  DEBUG: Selected option: {text}")
                    await asyncio.sleep(0.5)
                    return True

            # If no exact match, click first available option
            first_option = self.page.locator("mat-option").first
            if await first_option.count() > 0:
                text = await first_option.text_content()
                await first_option.click()
                print(f"  DEBUG: Selected first available option: {text}")
                await asyncio.sleep(0.5)
                return True

            return False

        except Exception as e:
            print(f"  DEBUG: Error selecting mat-option: {e}")
            return False

    async def select_visa_type(self) -> bool:
        """
        Select visa type (Short Stay).

        Returns:
            True if selection successful
        """
        logger.info(f"Selecting visa type: {self.config.visa_type}")

        try:
            # Wait for page to be ready
            await asyncio.sleep(2)

            # Take screenshot to see current state
            logger.debug(f"Current URL: {self.page.url}")

            # Select visa category - try mat-select first, then regular select
            category_selectors = [
                "mat-select[formcontrolname='missionCategory']",
                "mat-select:has-text('Category')",
                "#mat-select-0",
                "mat-select",
            ]

            category_options = ["Short Stay", "SHORT STAY", "Short stay"]

            for selector in category_selectors:
                if await self._element_exists(selector):
                    if await self._click_mat_select_option(selector, category_options):
                        logger.info("Selected visa category: Short Stay")
                        break

            await asyncio.sleep(1)

            # Select subcategory
            subcategory_selectors = [
                "mat-select[formcontrolname='missionCode']",
                "mat-select:has-text('Sub-Category')",
                "#mat-select-2",
            ]

            subcategory_options = [
                "All other Short Stay visas",
                "All kind of other short stay visas",
                "Other Short Stay",
                "Tourism",
                "Other",
            ]

            for selector in subcategory_selectors:
                if await self._element_exists(selector):
                    if await self._click_mat_select_option(selector, subcategory_options):
                        logger.info("Selected visa subcategory")
                        break

            await self.browser.human_behavior.random_delay(0.5, 1)
            self._current_state = PageState.VISA_TYPE_SELECTION
            return True

        except Exception as e:
            logger.exception("Failed to select visa type", e)
            return False

    async def select_center(self, center_name: str) -> bool:
        """
        Select visa center.

        Args:
            center_name: Name of the visa center

        Returns:
            True if selection successful
        """
        logger.info(f"Selecting visa center: {center_name}")

        try:
            await asyncio.sleep(1)

            # Center dropdown selectors for mat-select
            center_selectors = [
                "mat-select[formcontrolname='vacCode']",
                "mat-select:has-text('Centre')",
                "mat-select:has-text('Visa Application')",
                "#mat-select-4",
            ]

            # Different variations of center name
            center_options = [
                center_name,
                center_name.upper(),
                center_name.lower(),
                center_name.replace(" ", ""),
                f"Russia-{center_name}",
                f"RUS-{center_name}",
            ]

            for selector in center_selectors:
                if await self._element_exists(selector):
                    if await self._click_mat_select_option(selector, center_options):
                        logger.info(f"Selected visa center: {center_name}")
                        break

            await self.browser.human_behavior.random_delay(0.5, 1)
            self._current_state = PageState.CENTER_SELECTION
            return True

        except Exception as e:
            logger.exception(f"Failed to select center {center_name}", e)
            return False

    async def select_applicants_count(self) -> bool:
        """
        Select number of applicants.

        Returns:
            True if selection successful
        """
        count = self.config.applicants_count
        logger.info(f"Selecting applicants count: {count}")

        try:
            # Applicants dropdown selectors
            applicants_selectors = [
                "mat-select[formcontrolname='noOfApplicants']",
                "mat-select:has-text('Applicant')",
                "#mat-select-6",
            ]

            for selector in applicants_selectors:
                if await self._element_exists(selector):
                    if await self._click_mat_select_option(selector, [str(count), f"{count} Applicant"]):
                        logger.info(f"Selected {count} applicant(s)")
                        break

            await self.browser.human_behavior.random_delay(0.3, 0.5)
            return True

        except Exception as e:
            logger.debug(f"Applicants selector not found or error: {e}")
            return True  # Non-critical

    async def click_continue(self) -> bool:
        """
        Click continue/submit button.

        Returns:
            True if clicked successfully
        """
        try:
            continue_selectors = [
                "button:has-text('Continue')",
                "input[value='Continue']",
                "button:has-text('Submit')",
                "button:has-text('Next')",
                "button:has-text('Proceed')",
                ".btn-continue",
                ".btn-primary",
            ]

            for selector in continue_selectors:
                if await self._element_exists(selector):
                    await self.browser.human_click(selector)
                    logger.debug(f"Clicked continue: {selector}")
                    await asyncio.sleep(2)
                    return True

            return False

        except Exception as e:
            logger.exception("Failed to click continue", e)
            return False

    # Track state for optimized checking
    _cycle_count = 0
    _step_in_cycle = 0  # 0-4 steps per cycle
    _reverse_order = False  # Alternate direction for less predictable pattern

    async def check_all_combinations(self) -> CheckResult:
        """
        OPTIMIZED STRATEGY with full human behavior simulation:

        Features:
        - Block detection (stops if "Access Restricted" detected)
        - Random long pauses (coffee breaks)
        - Human mistakes (occasional wrong clicks)
        - Gaussian timing (not uniform random)
        - Time-of-day speed variation
        - Mouse movements before clicks

        Cycle (forward):
          Step 0: Moscow (3 dropdowns) + "All kind of..." → check → PAUSE 30-60s
          Step 1: (only subcategory) → PRIME TIME → check → PAUSE 2-3 min
          Step 2: Nizhniy Novgorod (3 dropdowns) + "All kind of..." → check → PAUSE 3-5 min

        Cycle (reverse) - alternates for unpredictability.
        """
        start_time = datetime.now()
        human = self._get_human()

        try:
            # =====================================================================
            # 1. CHECK IF BLOCKED
            # =====================================================================
            is_blocked, block_reason = await human.check_if_blocked(self.page)
            if is_blocked:
                self._is_blocked = True
                self._block_reason = block_reason
                print(f"\n  🚫 BLOCKED: {block_reason}")
                print("  ⛔ Stopping bot to avoid further detection...")
                logger.error(f"Blocked by VFS: {block_reason}")
                return CheckResult(
                    state=PageState.BLOCKED,
                    error_message=f"Blocked: {block_reason}",
                    needs_retry=False,
                )

            # =====================================================================
            # 2. MAYBE TAKE A BREAK (coffee, phone call, etc)
            # =====================================================================
            should_break, break_duration = HumanBehavior.should_take_break(VFSNavigator._cycle_count)
            if should_break:
                reasons = [
                    "Coffee break",
                    "Phone call",
                    "Stretching",
                    "Quick snack",
                    "Checking phone",
                    "Bio break",
                ]
                await human.take_break(break_duration, random.choice(reasons))

            # =====================================================================
            # 3. CHECK URL
            # =====================================================================
            current_url = self.page.url
            if "application" not in current_url:
                print("  ⚠️ Not on application page!")
                return CheckResult(
                    state=PageState.ERROR,
                    error_message="Not on application page",
                    needs_retry=False,
                )

            step = VFSNavigator._step_in_cycle
            reverse = VFSNavigator._reverse_order

            print(f"\n[Cycle #{VFSNavigator._cycle_count + 1}, Step {step + 1}/3] {'(reverse)' if reverse else ''}")

            # =====================================================================
            # 4. MAYBE MAKE A HUMAN MISTAKE (10% chance)
            # =====================================================================
            await human.maybe_make_mistake(self.page, probability=0.10)

            # =====================================================================
            # 5. MAYBE DO RANDOM SCROLL (like browsing)
            # =====================================================================
            if random.random() < 0.2:
                await human.random_scroll()

            result = None
            pause_seconds = 0

            if not reverse:
                # FORWARD ORDER: Moscow → Moscow PRIME → Nizhniy
                if step == 0:
                    print("  🔄 Moscow + All kind of other short stay visas")
                    result = await self._check_single_combination(
                        "Moscow", "Moscow", "All kind of other short stay visas"
                    )
                    pause_seconds = HumanBehavior.gaussian_range(30, 60)

                elif step == 1:
                    print("  🔄 Moscow + PRIME TIME (only subcategory)")
                    result = await self._check_subcategory_only("Moscow PRIME", "PRIME TIME")
                    pause_seconds = HumanBehavior.gaussian_range(120, 180)

                elif step == 2:
                    print("  🔄 Nizhniy Novgorod + All kind of other short stay visas")
                    result = await self._check_single_combination(
                        "Nizhniy Novgorod", "Nizhniy Novgorod", "All kind of other short stay visas"
                    )
                    pause_seconds = HumanBehavior.gaussian_range(180, 300)
            else:
                # REVERSE ORDER: Nizhniy → Moscow → Moscow PRIME
                if step == 0:
                    print("  🔄 Nizhniy Novgorod + All kind of other short stay visas")
                    result = await self._check_single_combination(
                        "Nizhniy Novgorod", "Nizhniy Novgorod", "All kind of other short stay visas"
                    )
                    pause_seconds = HumanBehavior.gaussian_range(30, 60)

                elif step == 1:
                    print("  🔄 Moscow + All kind of other short stay visas")
                    result = await self._check_single_combination(
                        "Moscow", "Moscow", "All kind of other short stay visas"
                    )
                    pause_seconds = HumanBehavior.gaussian_range(30, 60)

                elif step == 2:
                    print("  🔄 Moscow + PRIME TIME (only subcategory)")
                    result = await self._check_subcategory_only("Moscow PRIME", "PRIME TIME")
                    pause_seconds = HumanBehavior.gaussian_range(180, 300)

            # =====================================================================
            # 6. CHECK FOR BLOCK AFTER ACTION (sometimes appears after interaction)
            # =====================================================================
            is_blocked, block_reason = await human.check_if_blocked(self.page)
            if is_blocked:
                self._is_blocked = True
                self._block_reason = block_reason
                print(f"\n  🚫 BLOCKED AFTER ACTION: {block_reason}")
                logger.error(f"Blocked by VFS after action: {block_reason}")
                return CheckResult(
                    state=PageState.BLOCKED,
                    error_message=f"Blocked: {block_reason}",
                    needs_retry=False,
                )

            # =====================================================================
            # 7. PROCESS RESULT
            # =====================================================================
            if result and result.state == PageState.SLOT_SELECTION and result.slots:
                print(f"  🎉 SLOTS FOUND!")
                return result
            elif result and result.state == PageState.NO_SLOTS:
                print(f"  ❌ No slots")
            elif result and result.state == PageState.ERROR:
                print(f"  ⚠️ Error: {result.error_message}")

            # =====================================================================
            # 8. MOVE TO NEXT STEP
            # =====================================================================
            VFSNavigator._step_in_cycle = (step + 1) % 3
            if VFSNavigator._step_in_cycle == 0:
                VFSNavigator._cycle_count += 1
                VFSNavigator._reverse_order = not VFSNavigator._reverse_order
                print(f"\n  ✅ Cycle complete. Next: {'reverse' if VFSNavigator._reverse_order else 'forward'}")

            # =====================================================================
            # 9. WAIT WITH HUMAN-LIKE TIMING (time-of-day adjusted)
            # =====================================================================
            if pause_seconds > 0:
                # Apply time-of-day multiplier
                multiplier = HumanBehavior.get_time_multiplier()
                actual_pause = pause_seconds * multiplier
                print(f"  ⏳ Waiting {int(actual_pause)}s...")
                await asyncio.sleep(actual_pause)

            duration = (datetime.now() - start_time).total_seconds()
            logger.check_completed(duration)
            return CheckResult(state=PageState.NO_SLOTS)

        except Exception as e:
            logger.exception("Error checking", e)
            return CheckResult(
                state=PageState.ERROR,
                error_message=str(e),
                needs_retry=True,
            )

    async def _passive_check(self, combo_name: str) -> CheckResult:
        """
        Quick passive check - just read current page state.
        In case VFS auto-updates via JavaScript.
        """
        try:
            page_text = await self.page.content()
            page_text_lower = page_text.lower()

            # Check for "no slots" message
            if "no appointment slots are currently available" in page_text_lower:
                return CheckResult(state=PageState.NO_SLOTS)

            # Check for active Continue button
            continue_button = self.page.locator("button:has-text('Continue')").first
            if await continue_button.count() > 0:
                is_disabled = await continue_button.get_attribute("disabled")
                if is_disabled is None:
                    logger.slot_found(combo_name, "Available", "Check website")
                    slot = SlotInfo(
                        center=combo_name,
                        date="Available - check website",
                        time_slots=["Continue button active"],
                        booking_url=self.page.url,
                    )
                    return CheckResult(state=PageState.SLOT_SELECTION, slots=[slot])

            return CheckResult(state=PageState.NO_SLOTS)

        except Exception as e:
            return CheckResult(state=PageState.ERROR, error_message=str(e))

    async def _check_subcategory_only(self, combo_name: str, subcategory_text: str) -> CheckResult:
        """
        Change ONLY the subcategory dropdown (index 2) - minimal interaction.
        Used when staying on same city to check different visa type.

        Args:
            combo_name: Display name for logging
            subcategory_text: Text to match in subcategory dropdown

        Returns:
            CheckResult with slot information
        """
        try:
            print(f"  Changing only subcategory to '{subcategory_text}'...")

            # Only click subcategory dropdown (index 2)
            subcategory_selected = await self._select_dropdown_by_index(2, subcategory_text)
            if not subcategory_selected:
                return CheckResult(
                    state=PageState.ERROR,
                    error_message=f"Could not select subcategory: {subcategory_text}",
                )

            # Check result
            result = await self._check_slot_availability(combo_name)
            return result

        except Exception as e:
            print(f"  ERROR: {e}")
            return CheckResult(
                state=PageState.ERROR,
                error_message=str(e),
                needs_retry=True,
            )

    async def _check_single_combination(
        self, combo_name: str, center_text: str, subcategory_text: str
    ) -> CheckResult:
        """
        Check slots for a single combination of center and subcategory.

        Dropdowns appear in order (each one loads after previous selection):
        - Dropdown 0: Center (Moscow / Nizhniy Novgorod)
        - Dropdown 1: Category (Short Stay) - appears after center selected
        - Dropdown 2: Subcategory (All kind of... / PRIME TIME) - appears after category selected

        Args:
            combo_name: Display name for this combination
            center_text: Text to match in center dropdown
            subcategory_text: Text to match in subcategory dropdown

        Returns:
            CheckResult with slot information
        """
        try:
            # Step 1: Select Center (first dropdown, index 0)
            print(f"\n  Step 1: Selecting center '{center_text}'...")
            center_selected = await self._select_dropdown_by_index(0, center_text)
            if not center_selected:
                return CheckResult(
                    state=PageState.ERROR,
                    error_message=f"Could not select center: {center_text}",
                )

            # Step 2: Select Category - Short Stay (second dropdown, index 1)
            # This dropdown appears after center is selected
            print(f"\n  Step 2: Selecting category 'Short Stay'...")
            category_selected = await self._select_dropdown_by_index(1, "Short Stay")
            if not category_selected:
                return CheckResult(
                    state=PageState.ERROR,
                    error_message="Could not select category: Short Stay",
                )

            # Step 3: Select Subcategory (third dropdown, index 2)
            # This dropdown appears after category is selected
            print(f"\n  Step 3: Selecting subcategory '{subcategory_text}'...")
            subcategory_selected = await self._select_dropdown_by_index(2, subcategory_text)
            if not subcategory_selected:
                return CheckResult(
                    state=PageState.ERROR,
                    error_message=f"Could not select subcategory: {subcategory_text}",
                )

            # Step 4: Check result - look for "no slots" message OR active Continue button
            print(f"\n  Step 4: Checking for available slots...")
            result = await self._check_slot_availability(combo_name)

            return result

        except Exception as e:
            print(f"  ERROR: {e}")
            return CheckResult(
                state=PageState.ERROR,
                error_message=str(e),
                needs_retry=True,
            )

    async def _check_slot_availability(self, combo_name: str) -> CheckResult:
        """
        Check if slots are available after selecting form options.

        Looks for:
        1. "no appointment slots are currently available" message -> NO_SLOTS
        2. Active (not disabled) Continue button -> SLOTS AVAILABLE!

        Args:
            combo_name: Name of the combination being checked

        Returns:
            CheckResult
        """
        await asyncio.sleep(1)

        # Check for "no slots" message
        no_slots_texts = [
            "no appointment slots are currently available",
            "no slots available",
            "no appointment",
            "currently not available",
            "fully booked",
        ]

        page_text = await self.page.content()
        page_text_lower = page_text.lower()

        for text in no_slots_texts:
            if text.lower() in page_text_lower:
                print(f"  Result: NO SLOTS (found '{text}')")
                logger.no_slots(combo_name)
                return CheckResult(state=PageState.NO_SLOTS)

        # Check for Continue button
        continue_button = self.page.locator("button:has-text('Continue')").first
        if await continue_button.count() > 0:
            # Check if button is enabled (not disabled)
            is_disabled = await continue_button.get_attribute("disabled")
            is_aria_disabled = await continue_button.get_attribute("aria-disabled")
            button_class = await continue_button.get_attribute("class") or ""

            print(f"  DEBUG: Continue button found")
            print(f"    disabled attr: {is_disabled}")
            print(f"    aria-disabled: {is_aria_disabled}")
            print(f"    classes: {button_class[:50]}...")

            # Button is active if not disabled
            if is_disabled is None and is_aria_disabled != "true" and "disabled" not in button_class:
                print(f"\n  🎉 SLOTS AVAILABLE! Continue button is active!")
                logger.slot_found(combo_name, "Available", "Check website")

                slot = SlotInfo(
                    center=combo_name,
                    date="Available - check website",
                    time_slots=["Continue button is active"],
                    booking_url=self.page.url,
                )
                return CheckResult(
                    state=PageState.SLOT_SELECTION,
                    slots=[slot],
                )
            else:
                print(f"  Result: Continue button exists but is DISABLED")
                return CheckResult(state=PageState.NO_SLOTS)

        # No clear indication - assume no slots
        print(f"  Result: No Continue button found, assuming no slots")
        return CheckResult(state=PageState.NO_SLOTS)

    async def check_slots_for_center(self, center_name: str) -> CheckResult:
        """
        Check available slots for a specific center.
        NOTE: This method now delegates to check_all_combinations for comprehensive checking.

        Args:
            center_name: Name of the visa center (used for logging)

        Returns:
            CheckResult with slot information
        """
        # Use the new comprehensive check
        return await self.check_all_combinations()

    async def _check_current_page_for_slots(self, center_name: str) -> CheckResult:
        """
        Check current page for available slots.

        Args:
            center_name: Center name for context

        Returns:
            CheckResult with findings
        """
        # Check for "No slots" message
        no_slots_indicators = [
            ":has-text('No appointment')",
            ":has-text('no slots')",
            ":has-text('No available')",
            ":has-text('fully booked')",
            ":has-text('not available')",
            ".no-slots-message",
            ".no-appointment",
        ]

        for selector in no_slots_indicators:
            if await self._element_exists(selector):
                logger.no_slots(center_name)
                return CheckResult(state=PageState.NO_SLOTS)

        # Check for queue message
        queue_indicators = [
            ":has-text('queue')",
            ":has-text('waiting list')",
            ".queue-message",
        ]

        for selector in queue_indicators:
            if await self._element_exists(selector):
                logger.warning(f"Queue detected for {center_name}")
                return CheckResult(state=PageState.QUEUE)

        # Check for available dates in calendar
        available_dates = await self._find_available_dates()
        if available_dates:
            slots = []
            for date_str in available_dates:
                time_slots = await self._get_time_slots_for_date(date_str)
                if time_slots:
                    slot = SlotInfo(
                        center=center_name,
                        date=date_str,
                        time_slots=time_slots,
                        booking_url=self.page.url,
                    )
                    slots.append(slot)
                    logger.slot_found(center_name, date_str, ", ".join(time_slots))

            if slots:
                return CheckResult(
                    state=PageState.SLOT_SELECTION,
                    slots=slots,
                )

        # No clear indication of slots
        logger.no_slots(center_name)
        return CheckResult(state=PageState.NO_SLOTS)

    async def _find_available_dates(self) -> List[str]:
        """Find available dates in calendar."""
        available_dates = []

        try:
            # Look for calendar container
            calendar_selectors = [
                ".calendar",
                ".datepicker",
                "#calendar",
                ".date-picker",
                "[data-calendar]",
            ]

            calendar_found = False
            for selector in calendar_selectors:
                if await self._element_exists(selector):
                    calendar_found = True
                    break

            if not calendar_found:
                return []

            # Find available (clickable) dates
            available_date_selectors = [
                ".day:not(.disabled):not(.past)",
                "td.available",
                ".available-date",
                ".day.active:not(.disabled)",
                "td:not(.disabled):not(.blocked) a",
            ]

            for selector in available_date_selectors:
                dates = self.page.locator(selector)
                count = await dates.count()

                if count > 0:
                    for i in range(min(count, 10)):  # Check up to 10 dates
                        try:
                            date_element = dates.nth(i)
                            date_text = await date_element.text_content()

                            # Try to get date from various attributes
                            if not date_text:
                                date_text = await date_element.get_attribute("data-date")
                            if not date_text:
                                date_text = await date_element.get_attribute("title")

                            if date_text and date_text.strip():
                                available_dates.append(date_text.strip())
                        except Exception:
                            continue

                    if available_dates:
                        break

        except Exception as e:
            logger.debug(f"Error finding available dates: {e}")

        return available_dates

    async def _get_time_slots_for_date(self, date_str: str) -> List[str]:
        """Get available time slots for a specific date."""
        time_slots = []

        try:
            # Try to click on the date first
            date_selectors = [
                f"[data-date='{date_str}']",
                f":has-text('{date_str}')",
            ]

            for selector in date_selectors:
                if await self._element_exists(selector):
                    try:
                        await self.browser.human_click(selector)
                        await asyncio.sleep(1)
                        break
                    except Exception:
                        continue

            # Find time slot elements
            time_slot_selectors = [
                ".time-slot:not(.disabled)",
                ".slot-available",
                ".appointment-time",
                ".available-slot",
                "button.slot",
            ]

            for selector in time_slot_selectors:
                slots = self.page.locator(selector)
                count = await slots.count()

                if count > 0:
                    for i in range(count):
                        try:
                            slot_element = slots.nth(i)
                            slot_text = await slot_element.text_content()
                            if slot_text and slot_text.strip():
                                time_slots.append(slot_text.strip())
                        except Exception:
                            continue

                    if time_slots:
                        break

        except Exception as e:
            logger.debug(f"Error getting time slots: {e}")

        return time_slots

    async def _wait_for_element(self, selector: str, timeout: int = 30000) -> bool:
        """Wait for element to appear."""
        try:
            locator = self.page.locator(selector)
            await locator.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    async def _element_exists(self, selector: str) -> bool:
        """Check if element exists on page."""
        try:
            locator = self.page.locator(selector)
            count = await locator.count()
            return count > 0
        except Exception:
            return False

    async def take_screenshot(self, name: str = "screenshot") -> str:
        """
        Take screenshot of current page.

        Args:
            name: Screenshot file name

        Returns:
            Path to screenshot file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"logs/screenshots/{name}_{timestamp}.png"
        await self.browser.screenshot(path)
        return path

    async def reset_session(self) -> None:
        """Reset browser session for fresh start."""
        logger.info("Resetting session...")
        self._logged_in = False
        self._current_state = PageState.UNKNOWN
        await self.browser.clear_cookies()
        await self.browser.restart()
