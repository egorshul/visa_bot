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
        # Login
        "email_input": "input[type='email'], input[name='email'], #email",
        "password_input": "input[type='password'], input[name='password'], #password",
        "login_button": "button[type='submit'], .btn-login, #btnSubmit",
        "login_form": "form.login-form, #loginForm, form[action*='login']",

        # Navigation
        "new_booking_btn": "button:has-text('New Booking'), a:has-text('New Booking'), .new-booking",
        "schedule_appointment": "a:has-text('Schedule Appointment'), button:has-text('Schedule')",

        # Visa type selection
        "visa_category": "select#VisaCategory, select[name='VisaCategory'], .visa-category select",
        "visa_subcategory": "select#VisaSubCategory, select[name='VisaSubCategory'], .visa-subcategory select",
        "short_stay_option": "option:has-text('Short Stay'), option[value*='short']",

        # Center selection
        "center_dropdown": "select#VisaCentre, select[name='VisaCentre'], .visa-centre select",
        "center_option": "option:has-text('{center}')",

        # Applicants
        "applicants_dropdown": "select#NumberOfApplicants, select[name='applicants']",

        # Continue/Submit buttons
        "continue_button": "button:has-text('Continue'), input[value='Continue'], .btn-continue",
        "submit_button": "button[type='submit'], input[type='submit']",

        # Calendar and slots
        "calendar_container": ".calendar-container, .datepicker, #calendar",
        "available_date": ".day:not(.disabled), .available-date, td.active:not(.disabled)",
        "time_slot": ".time-slot:not(.disabled), .slot-available, .appointment-slot",
        "slot_time_text": ".slot-time, .time-text",

        # Messages
        "no_slots_message": ".no-slots, .no-appointment, :has-text('No appointment')",
        "queue_message": ".queue-message, :has-text('queue'), :has-text('Queue')",
        "error_message": ".error-message, .alert-danger, .error",

        # General
        "loading_spinner": ".loading, .spinner, .loader",
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

    async def login(self) -> bool:
        """
        Log in to VFS Global account.

        Returns:
            True if login successful
        """
        logger.info("Starting login process...")

        try:
            # Navigate to login page
            login_url = self.config.get_login_url()
            await self.browser.navigate(login_url)

            # Wait for page to load
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

            # Click login button
            logger.debug("Clicking login button...")
            await self.browser.human_click(self.SELECTORS["login_button"])

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
        Navigate to appointment booking page.

        Returns:
            True if navigation successful
        """
        logger.info("Navigating to appointment page...")

        try:
            # Try to find and click "New Booking" or similar button
            new_booking_selectors = [
                "button:has-text('New Booking')",
                "a:has-text('New Booking')",
                "button:has-text('Schedule Appointment')",
                "a:has-text('Schedule Appointment')",
                ".new-booking-btn",
                "#newBooking",
            ]

            for selector in new_booking_selectors:
                if await self._element_exists(selector):
                    await self.browser.human_click(selector)
                    await asyncio.sleep(2)
                    await self.browser.wait_for_load()
                    logger.debug(f"Clicked: {selector}")
                    break

            # Navigate directly to application URL if buttons not found
            app_url = self.config.get_application_url()
            if not await self._is_on_application_page():
                logger.debug(f"Direct navigation to: {app_url}")
                await self.browser.navigate(app_url)
                await self.browser.wait_for_load()

            self._current_state = PageState.APPLICATION_PAGE
            return True

        except Exception as e:
            logger.exception("Failed to navigate to appointment page", e)
            return False

    async def _is_on_application_page(self) -> bool:
        """Check if on application/appointment page."""
        url = self.page.url
        return bool(
            re.search(self.URL_PATTERNS["application"], url) or
            re.search(self.URL_PATTERNS["appointment"], url)
        )

    async def select_visa_type(self) -> bool:
        """
        Select visa type (Short Stay).

        Returns:
            True if selection successful
        """
        logger.info(f"Selecting visa type: {self.config.visa_type}")

        try:
            # Wait for visa category dropdown
            await self._wait_for_element(self.SELECTORS["visa_category"], timeout=10000)

            # Select visa category (Short Stay)
            category_dropdown = self.page.locator(self.SELECTORS["visa_category"])
            if await category_dropdown.count() > 0:
                await category_dropdown.select_option(label="Short Stay")
                await self.browser.human_behavior.random_delay(0.5, 1)

            # Select subcategory if present
            subcategory_dropdown = self.page.locator(self.SELECTORS["visa_subcategory"])
            if await subcategory_dropdown.count() > 0:
                await asyncio.sleep(1)  # Wait for subcategory to load

                # Try to select "All other short stay visas" or similar
                subcategory_options = [
                    "All other Short Stay visas",
                    "All kind of other short stay visas",
                    "Other Short Stay",
                    "Tourism",
                ]

                for option in subcategory_options:
                    try:
                        await subcategory_dropdown.select_option(label=option)
                        logger.debug(f"Selected subcategory: {option}")
                        break
                    except Exception:
                        continue

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
            # Wait for center dropdown
            await self._wait_for_element(self.SELECTORS["center_dropdown"], timeout=10000)

            # Select center
            center_dropdown = self.page.locator(self.SELECTORS["center_dropdown"])
            if await center_dropdown.count() > 0:
                # Try different name variations
                center_variations = [
                    center_name,
                    center_name.upper(),
                    center_name.lower(),
                    center_name.title(),
                ]

                for variation in center_variations:
                    try:
                        await center_dropdown.select_option(label=variation)
                        logger.debug(f"Selected center: {variation}")
                        break
                    except Exception:
                        # Try partial match
                        try:
                            options = await center_dropdown.locator("option").all()
                            for option in options:
                                text = await option.text_content()
                                if text and center_name.lower() in text.lower():
                                    value = await option.get_attribute("value")
                                    await center_dropdown.select_option(value=value)
                                    logger.debug(f"Selected center by value: {text}")
                                    break
                        except Exception:
                            continue

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

        try:
            applicants_dropdown = self.page.locator(self.SELECTORS["applicants_dropdown"])
            if await applicants_dropdown.count() > 0:
                await applicants_dropdown.select_option(value=str(count))
                logger.debug(f"Selected {count} applicant(s)")
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
            # Ensure we're logged in
            if not self._logged_in:
                if not await self.login():
                    return CheckResult(
                        state=PageState.ERROR,
                        error_message="Login failed",
                        needs_retry=True,
                    )

            # Navigate to appointment page
            await self.navigate_to_appointment()

            # Select visa type
            await self.select_visa_type()

            # Select center
            await self.select_center(center_name)

            # Select applicants count
            await self.select_applicants_count()

            # Click continue to proceed to calendar
            await self.click_continue()

            # Wait for page to load
            await asyncio.sleep(3)
            await self.browser.wait_for_load()

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
