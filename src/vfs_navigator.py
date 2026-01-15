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

    async def check_slots_for_center(self, center_name: str) -> CheckResult:
        """
        Check available slots for a specific center.

        Args:
            center_name: Name of the visa center

        Returns:
            CheckResult with slot information
        """
        logger.check_started(center_name)
        start_time = datetime.now()

        try:
            # DEBUG: Print current state
            current_url = self.page.url
            print(f"\n{'='*50}")
            print(f"DEBUG: Current URL: {current_url}")
            print(f"DEBUG: Checking center: {center_name}")
            print(f"{'='*50}\n")

            # Check if on application page
            if "application" not in current_url:
                print("ERROR: Not on application page!")
                print(f"Please open: {self.config.get_application_url()}")
                print("Then restart the bot.")
                return CheckResult(
                    state=PageState.ERROR,
                    error_message="Not on application page. Please navigate manually.",
                    needs_retry=False,
                )

            # Check if logged in (simple check - if we see mat-select, we're probably logged in)
            mat_selects = await self.page.locator("mat-select").all()
            if len(mat_selects) == 0:
                print("ERROR: No form elements found. You might be logged out.")
                print("Please login manually and refresh the page.")
                return CheckResult(
                    state=PageState.ERROR,
                    error_message="Not logged in. Please login manually.",
                    needs_retry=False,
                )

            print(f"DEBUG: Page looks good, found {len(mat_selects)} dropdowns")

            # DEBUG: Find all mat-select elements on page
            mat_selects = await self.page.locator("mat-select").all()
            print(f"DEBUG: Found {len(mat_selects)} mat-select elements")
            for i, ms in enumerate(mat_selects):
                try:
                    text = await ms.text_content()
                    print(f"  mat-select[{i}]: {text[:50] if text else 'empty'}...")
                except:
                    pass

            # Select visa type
            print("\nDEBUG: Selecting visa type...")
            await self.select_visa_type()

            # Select center
            print(f"\nDEBUG: Selecting center: {center_name}...")
            await self.select_center(center_name)

            # Select applicants count
            print("\nDEBUG: Selecting applicants count...")
            await self.select_applicants_count()

            # Click continue to proceed to calendar
            print("\nDEBUG: Clicking continue...")
            await self.click_continue()

            # Wait for page to load
            await asyncio.sleep(3)
            await self.browser.wait_for_load()

            print(f"\nDEBUG: After continue URL: {self.page.url}")

            # Check for CAPTCHA
            if self.captcha_solver:
                captcha_solved = await self.captcha_solver.check_and_solve(self.page)
                if not captcha_solved:
                    return CheckResult(
                        state=PageState.CAPTCHA,
                        error_message="CAPTCHA appeared",
                        needs_retry=True,
                    )

            # Check page state and available slots
            result = await self._check_current_page_for_slots(center_name)

            duration = (datetime.now() - start_time).total_seconds()
            logger.check_completed(duration)

            return result

        except Exception as e:
            logger.exception(f"Error checking slots for {center_name}", e)
            return CheckResult(
                state=PageState.ERROR,
                error_message=str(e),
                needs_retry=True,
            )

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
