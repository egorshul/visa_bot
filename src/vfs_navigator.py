"""
VFS Global website navigation module.

Handles login, navigation, and slot availability checking.
"""

import asyncio
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

        Args:
            index: Index of the mat-select (0 = first, 1 = second, etc.)
            option_text: Text of the option to select
            wait_for_load: Whether to wait for loading after selection

        Returns:
            True if option selected successfully
        """
        try:
            # Check for Cloudflare first
            if await self._check_cloudflare_captcha():
                print("  DEBUG: Cloudflare detected during dropdown selection!")
                captcha_passed = await self.wait_for_cloudflare_to_pass()
                if not captcha_passed:
                    return False

            # Wait for dropdowns to be present
            print(f"  DEBUG: Looking for mat-select[{index}]...")

            # Wait up to 10 seconds for enough dropdowns to appear
            for attempt in range(20):
                mat_selects = await self.page.locator("mat-select").all()
                if len(mat_selects) > index:
                    break
                # Check for Cloudflare while waiting
                if await self._check_cloudflare_captcha():
                    print("  DEBUG: Cloudflare appeared while waiting for dropdown!")
                    captcha_passed = await self.wait_for_cloudflare_to_pass()
                    if not captcha_passed:
                        return False
                print(f"  DEBUG: Found {len(mat_selects)} dropdowns, waiting for index {index}...")
                await asyncio.sleep(0.5)

            mat_selects = await self.page.locator("mat-select").all()
            print(f"  DEBUG: Total mat-selects on page: {len(mat_selects)}")

            if index >= len(mat_selects):
                print(f"  DEBUG: mat-select[{index}] not found! Only {len(mat_selects)} dropdowns exist.")
                return False

            dropdown = mat_selects[index]

            # Get current value
            current_text = await dropdown.text_content()
            print(f"  DEBUG: mat-select[{index}] current value: '{current_text[:50] if current_text else 'empty'}'")
            print(f"  DEBUG: mat-select[{index}] selecting: '{option_text}'")

            # Click to open dropdown
            await dropdown.click()
            await asyncio.sleep(1)

            # Wait for options panel to appear
            try:
                await self.page.wait_for_selector("mat-option", timeout=5000)
            except:
                print(f"  DEBUG: mat-select[{index}] No mat-option appeared after click")
                return False

            # List all available options
            all_options = await self.page.locator("mat-option").all()
            print(f"  DEBUG: mat-select[{index}] available options ({len(all_options)}):")
            for opt in all_options:
                try:
                    opt_text = await opt.text_content()
                    print(f"    - '{opt_text.strip() if opt_text else ''}'")
                except:
                    pass

            # Find and click the option containing our text
            option = self.page.locator(f"mat-option:has-text('{option_text}')").first
            if await option.count() > 0:
                await option.click()
                print(f"  DEBUG: mat-select[{index}] SELECTED: {option_text}")

                # Wait for loading after selection
                if wait_for_load:
                    print(f"  DEBUG: Waiting for page to load after selection...")
                    await asyncio.sleep(2)
                    # Wait for any spinner to disappear
                    try:
                        spinner = self.page.locator("mat-spinner, .loading, .spinner")
                        if await spinner.count() > 0:
                            await spinner.wait_for(state="hidden", timeout=10000)
                    except:
                        pass

                return True

            print(f"  DEBUG: mat-select[{index}] Option '{option_text}' not found!")

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

    async def check_all_combinations(self) -> CheckResult:
        """
        Check available slots for ALL combinations of centers and visa types.

        Combinations to check:
        - Moscow + Short Stay + All kind of other short stay visas
        - Moscow + Short Stay + PRIME TIME (65 euros)
        - Nizhniy Novgorod + Short Stay + All kind of other short stay visas

        Returns:
            CheckResult with slot information (if found)
        """
        logger.info("Starting check of all combinations...")
        start_time = datetime.now()

        # Define all combinations to try
        # Format: (center_name, center_text, subcategory_text)
        combinations = [
            ("Moscow", "Moscow", "All kind of other short stay visas"),
            ("Moscow PRIME", "Moscow", "PRIME TIME"),
            ("Nizhniy Novgorod", "Nizhniy Novgorod", "All kind of other short stay visas"),
        ]

        all_slots = []

        try:
            # Check for Cloudflare CAPTCHA first
            if await self._check_cloudflare_captcha():
                captcha_passed = await self.wait_for_cloudflare_to_pass()
                if not captcha_passed:
                    return CheckResult(
                        state=PageState.CAPTCHA,
                        error_message="Cloudflare CAPTCHA timeout",
                        needs_retry=True,
                    )

            # Check if on application page
            current_url = self.page.url
            print(f"\n{'='*60}")
            print(f"DEBUG: Current URL: {current_url}")
            print(f"DEBUG: Starting slot check for ALL combinations")
            print(f"{'='*60}\n")

            if "application" not in current_url:
                print("ERROR: Not on application page!")
                print(f"Please open: {self.config.get_application_url()}")
                return CheckResult(
                    state=PageState.ERROR,
                    error_message="Not on application page. Please navigate manually.",
                    needs_retry=False,
                )

            # Check if logged in (wait a bit for page to load)
            mat_selects = await self.page.locator("mat-select").all()
            if len(mat_selects) < 1:
                # Maybe page is still loading or Cloudflare appeared
                await asyncio.sleep(2)
                if await self._check_cloudflare_captcha():
                    captcha_passed = await self.wait_for_cloudflare_to_pass()
                    if not captcha_passed:
                        return CheckResult(
                            state=PageState.CAPTCHA,
                            error_message="Cloudflare CAPTCHA timeout",
                            needs_retry=True,
                        )
                mat_selects = await self.page.locator("mat-select").all()

            if len(mat_selects) < 1:
                print(f"ERROR: No dropdowns found. You might be logged out.")
                return CheckResult(
                    state=PageState.ERROR,
                    error_message="Not logged in or page not loaded. Please login/refresh.",
                    needs_retry=False,
                )

            print(f"DEBUG: Found {len(mat_selects)} mat-select dropdowns - page looks good!")

            # Try each combination
            for combo_name, center_text, subcategory_text in combinations:
                # Check for Cloudflare between combinations
                if await self._check_cloudflare_captcha():
                    print("\n⚠️  Cloudflare appeared between checks!")
                    captcha_passed = await self.wait_for_cloudflare_to_pass()
                    if not captcha_passed:
                        return CheckResult(
                            state=PageState.CAPTCHA,
                            error_message="Cloudflare CAPTCHA timeout",
                            needs_retry=True,
                        )

                print(f"\n{'-'*50}")
                print(f"CHECKING: {combo_name}")
                print(f"  Center: {center_text}")
                print(f"  Subcategory: {subcategory_text}")
                print(f"{'-'*50}")

                result = await self._check_single_combination(
                    combo_name, center_text, subcategory_text
                )

                if result.state == PageState.SLOT_SELECTION and result.slots:
                    print(f"\n🎉 SLOTS FOUND for {combo_name}!")
                    all_slots.extend(result.slots)
                elif result.state == PageState.NO_SLOTS:
                    print(f"  No slots for {combo_name}")
                elif result.state == PageState.ERROR:
                    print(f"  Error checking {combo_name}: {result.error_message}")
                elif result.state == PageState.CAPTCHA:
                    # Cloudflare appeared during check
                    return result

                # Small delay between combinations
                await asyncio.sleep(2)

            duration = (datetime.now() - start_time).total_seconds()
            logger.check_completed(duration)

            if all_slots:
                return CheckResult(
                    state=PageState.SLOT_SELECTION,
                    slots=all_slots,
                )
            else:
                return CheckResult(state=PageState.NO_SLOTS)

        except Exception as e:
            logger.exception("Error checking combinations", e)
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
