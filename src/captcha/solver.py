"""
CAPTCHA detection and solving module.

Detects CAPTCHA presence and integrates with solving services.
"""

import asyncio
import base64
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

import httpx

if TYPE_CHECKING:
    from playwright.async_api import Page

from ..utils.logger import BotLogger

logger = BotLogger("CAPTCHA")


class CaptchaType(Enum):
    """Types of CAPTCHA."""

    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    IMAGE_CAPTCHA = "image"
    CLOUDFLARE = "cloudflare"
    UNKNOWN = "unknown"


@dataclass
class CaptchaInfo:
    """Information about detected CAPTCHA."""

    captcha_type: CaptchaType
    site_key: Optional[str] = None
    page_url: Optional[str] = None
    data_s: Optional[str] = None  # For some reCAPTCHA implementations


class CaptchaDetector:
    """
    Detects CAPTCHA presence on page.
    """

    # Common CAPTCHA selectors
    RECAPTCHA_SELECTORS = [
        ".g-recaptcha",
        "[data-sitekey]",
        "iframe[src*='recaptcha']",
        "#recaptcha",
    ]

    HCAPTCHA_SELECTORS = [
        ".h-captcha",
        "[data-hcaptcha-sitekey]",
        "iframe[src*='hcaptcha']",
    ]

    CLOUDFLARE_SELECTORS = [
        "#challenge-running",
        "#challenge-form",
        ".cf-browser-verification",
        "#cf-please-wait",
        ".cf-turnstile",
        "iframe[src*='challenges.cloudflare.com']",
    ]

    TURNSTILE_SELECTORS = [
        ".cf-turnstile",
        "[data-sitekey]",
        "iframe[src*='challenges.cloudflare.com/turnstile']",
    ]

    IMAGE_CAPTCHA_SELECTORS = [
        "img[src*='captcha']",
        "#captcha-image",
        ".captcha-img",
    ]

    async def detect(self, page: "Page") -> Optional[CaptchaInfo]:
        """
        Detect CAPTCHA on page.

        Args:
            page: Playwright page instance

        Returns:
            CaptchaInfo if CAPTCHA found, None otherwise
        """
        page_url = page.url

        # Check for Cloudflare challenge / Turnstile
        for selector in self.CLOUDFLARE_SELECTORS:
            if await self._element_exists(page, selector):
                site_key = await self._get_turnstile_site_key(page)
                logger.warning(f"Cloudflare challenge detected, turnstile sitekey: {site_key}")
                return CaptchaInfo(
                    captcha_type=CaptchaType.CLOUDFLARE,
                    site_key=site_key,
                    page_url=page_url,
                )

        # Check for reCAPTCHA
        for selector in self.RECAPTCHA_SELECTORS:
            if await self._element_exists(page, selector):
                site_key = await self._get_recaptcha_site_key(page)
                logger.warning(f"reCAPTCHA detected, site_key: {site_key}")
                return CaptchaInfo(
                    captcha_type=CaptchaType.RECAPTCHA_V2,
                    site_key=site_key,
                    page_url=page_url,
                )

        # Check for hCaptcha
        for selector in self.HCAPTCHA_SELECTORS:
            if await self._element_exists(page, selector):
                site_key = await self._get_hcaptcha_site_key(page)
                logger.warning(f"hCaptcha detected, site_key: {site_key}")
                return CaptchaInfo(
                    captcha_type=CaptchaType.HCAPTCHA,
                    site_key=site_key,
                    page_url=page_url,
                )

        # Check for image CAPTCHA
        for selector in self.IMAGE_CAPTCHA_SELECTORS:
            if await self._element_exists(page, selector):
                logger.warning("Image CAPTCHA detected")
                return CaptchaInfo(
                    captcha_type=CaptchaType.IMAGE_CAPTCHA,
                    page_url=page_url,
                )

        return None

    async def _element_exists(self, page: "Page", selector: str) -> bool:
        """Check if element exists on page."""
        try:
            locator = page.locator(selector)
            count = await locator.count()
            return count > 0
        except Exception:
            return False

    async def _get_recaptcha_site_key(self, page: "Page") -> Optional[str]:
        """Extract reCAPTCHA site key from page."""
        try:
            # Try data-sitekey attribute
            element = page.locator("[data-sitekey]").first
            if await element.count() > 0:
                return await element.get_attribute("data-sitekey")

            # Try from iframe src
            iframe = page.locator("iframe[src*='recaptcha']").first
            if await iframe.count() > 0:
                src = await iframe.get_attribute("src")
                if src and "k=" in src:
                    return src.split("k=")[1].split("&")[0]

        except Exception as e:
            logger.debug(f"Failed to extract reCAPTCHA site key: {e}")

        return None

    async def _get_hcaptcha_site_key(self, page: "Page") -> Optional[str]:
        """Extract hCaptcha site key from page."""
        try:
            element = page.locator("[data-hcaptcha-sitekey], [data-sitekey]").first
            if await element.count() > 0:
                site_key = await element.get_attribute("data-hcaptcha-sitekey")
                if not site_key:
                    site_key = await element.get_attribute("data-sitekey")
                return site_key
        except Exception as e:
            logger.debug(f"Failed to extract hCaptcha site key: {e}")

        return None

    async def _get_turnstile_site_key(self, page: "Page") -> Optional[str]:
        """Extract Cloudflare Turnstile site key from page."""
        try:
            # Try cf-turnstile element
            element = page.locator(".cf-turnstile[data-sitekey]").first
            if await element.count() > 0:
                return await element.get_attribute("data-sitekey")

            # Try any element with data-sitekey near turnstile
            element = page.locator("[data-sitekey]").first
            if await element.count() > 0:
                return await element.get_attribute("data-sitekey")

            # Try to extract from iframe src
            iframe = page.locator("iframe[src*='challenges.cloudflare.com']").first
            if await iframe.count() > 0:
                src = await iframe.get_attribute("src")
                if src and "sitekey=" in src:
                    return src.split("sitekey=")[1].split("&")[0]

            # Try to get from page scripts
            site_key = await page.evaluate("""
                () => {
                    // Check for turnstile in window
                    if (window.turnstile && window.turnstile.getResponse) {
                        return null; // Already solved
                    }
                    // Look for sitekey in scripts
                    const scripts = document.querySelectorAll('script');
                    for (const script of scripts) {
                        const match = script.textContent.match(/sitekey['":\s]+([a-zA-Z0-9_-]+)/);
                        if (match) return match[1];
                    }
                    return null;
                }
            """)
            if site_key:
                return site_key

        except Exception as e:
            logger.debug(f"Failed to extract Turnstile site key: {e}")

        return None


class CaptchaSolver:
    """
    CAPTCHA solving integration with external services.
    """

    def __init__(
        self,
        service: str = "2captcha",
        api_key: str = "",
        timeout: int = 120,
        auto_solve: bool = False,
    ):
        """
        Initialize CAPTCHA solver.

        Args:
            service: Service to use ("2captcha" or "anticaptcha")
            api_key: API key for the service
            timeout: Timeout for solving in seconds
            auto_solve: Whether to automatically solve CAPTCHAs
        """
        self.service = service
        self.api_key = api_key
        self.timeout = timeout
        self.auto_solve = auto_solve
        self.detector = CaptchaDetector()

        # Service endpoints
        self._endpoints = {
            "2captcha": {
                "submit": "https://2captcha.com/in.php",
                "result": "https://2captcha.com/res.php",
            },
            "anticaptcha": {
                "submit": "https://api.anti-captcha.com/createTask",
                "result": "https://api.anti-captcha.com/getTaskResult",
            },
        }

    async def check_and_solve(self, page: "Page") -> bool:
        """
        Check for CAPTCHA and attempt to solve it.

        Args:
            page: Playwright page instance

        Returns:
            True if no CAPTCHA or successfully solved, False otherwise
        """
        captcha_info = await self.detector.detect(page)

        if captcha_info is None:
            return True

        logger.info(f"CAPTCHA detected: {captcha_info.captcha_type.value}")

        if not self.auto_solve or not self.api_key:
            logger.warning("Auto-solve disabled or no API key configured")
            return False

        # Handle different CAPTCHA types
        if captcha_info.captcha_type == CaptchaType.CLOUDFLARE:
            return await self._handle_cloudflare(page, captcha_info)

        if captcha_info.captcha_type == CaptchaType.RECAPTCHA_V2:
            return await self._solve_recaptcha_v2(page, captcha_info)

        if captcha_info.captcha_type == CaptchaType.HCAPTCHA:
            return await self._solve_hcaptcha(page, captcha_info)

        logger.warning(f"Unsupported CAPTCHA type: {captcha_info.captcha_type}")
        return False

    async def _handle_cloudflare(self, page: "Page", captcha_info: CaptchaInfo = None) -> bool:
        """
        Handle Cloudflare challenge using Turnstile solver.

        Args:
            page: Playwright page instance
            captcha_info: Optional CAPTCHA info with sitekey

        Returns:
            True if challenge passed
        """
        logger.info("Handling Cloudflare Turnstile challenge...")

        # Try to get sitekey if not provided
        site_key = captcha_info.site_key if captcha_info else None
        if not site_key:
            site_key = await self.detector._get_turnstile_site_key(page)

        # If we have API key and sitekey, try automatic solving
        if self.api_key and site_key:
            logger.info(f"Attempting automatic Turnstile solve (sitekey: {site_key[:20]}...)")
            token = await self._solve_turnstile(site_key, page.url)

            if token:
                # Inject the token
                try:
                    await page.evaluate(f"""
                        (token) => {{
                            // Try to set turnstile response
                            const input = document.querySelector('[name="cf-turnstile-response"]');
                            if (input) {{
                                input.value = token;
                            }}
                            // Try callback
                            if (window.turnstile && window.turnstile.callback) {{
                                window.turnstile.callback(token);
                            }}
                            // Try to find and submit form
                            const form = document.querySelector('#challenge-form, form');
                            if (form && form.submit) {{
                                form.submit();
                            }}
                        }}
                    """, token)
                    logger.info("Turnstile token injected")
                    await asyncio.sleep(3)

                    # Check if challenge passed
                    for selector in CaptchaDetector.CLOUDFLARE_SELECTORS:
                        if await page.locator(selector).count() > 0:
                            continue
                    logger.info("Cloudflare challenge passed via auto-solve!")
                    return True
                except Exception as e:
                    logger.error(f"Failed to inject Turnstile token: {e}")

        # Fallback: wait for manual/automatic resolution
        logger.info("Waiting for Cloudflare challenge to complete (manual or auto)...")

        for i in range(60):  # Wait up to 2 minutes
            await asyncio.sleep(2)

            # Check if challenge is still present
            challenge_present = False
            for selector in CaptchaDetector.CLOUDFLARE_SELECTORS:
                try:
                    if await page.locator(selector).count() > 0:
                        challenge_present = True
                        break
                except Exception:
                    pass

            if not challenge_present:
                logger.info("Cloudflare challenge passed")
                return True

            if i % 10 == 0:
                logger.info(f"Still waiting for Cloudflare... ({i*2}s)")

        logger.error("Cloudflare challenge timeout")
        return False

    async def _solve_turnstile(self, site_key: str, page_url: str) -> Optional[str]:
        """
        Solve Cloudflare Turnstile using 2Captcha or Anti-Captcha.

        Args:
            site_key: Turnstile site key
            page_url: Page URL

        Returns:
            Token if solved, None otherwise
        """
        if self.service == "2captcha":
            return await self._solve_2captcha_turnstile(site_key, page_url)
        else:
            return await self._solve_anticaptcha_turnstile(site_key, page_url)

    async def _solve_2captcha_turnstile(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve Turnstile using 2Captcha service."""
        logger.info("Submitting Turnstile to 2Captcha...")
        async with httpx.AsyncClient() as client:
            # Submit task
            response = await client.get(
                self._endpoints["2captcha"]["submit"],
                params={
                    "key": self.api_key,
                    "method": "turnstile",
                    "sitekey": site_key,
                    "pageurl": page_url,
                    "json": 1,
                },
            )
            result = response.json()

            if result.get("status") != 1:
                logger.error(f"2Captcha submit error: {result.get('error_text', result)}")
                return None

            task_id = result["request"]
            logger.info(f"2Captcha Turnstile task submitted: {task_id}")

            # Wait for result
            return await self._wait_2captcha_result(client, task_id)

    async def _solve_anticaptcha_turnstile(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve Turnstile using Anti-Captcha service."""
        logger.info("Submitting Turnstile to Anti-Captcha...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._endpoints["anticaptcha"]["submit"],
                json={
                    "clientKey": self.api_key,
                    "task": {
                        "type": "TurnstileTaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": site_key,
                    },
                },
            )
            result = response.json()

            if result.get("errorId") != 0:
                logger.error(f"Anti-Captcha error: {result.get('errorDescription')}")
                return None

            task_id = result["taskId"]
            logger.info(f"Anti-Captcha Turnstile task submitted: {task_id}")
            return await self._wait_anticaptcha_result(client, task_id)

    async def _solve_recaptcha_v2(self, page: "Page", captcha_info: CaptchaInfo) -> bool:
        """
        Solve reCAPTCHA v2 using external service.

        Args:
            page: Playwright page instance
            captcha_info: CAPTCHA information

        Returns:
            True if solved successfully
        """
        if not captcha_info.site_key:
            logger.error("Cannot solve reCAPTCHA: site key not found")
            return False

        try:
            if self.service == "2captcha":
                token = await self._solve_2captcha_recaptcha(
                    captcha_info.site_key,
                    captcha_info.page_url,
                )
            else:
                token = await self._solve_anticaptcha_recaptcha(
                    captcha_info.site_key,
                    captcha_info.page_url,
                )

            if token:
                # Inject the token into the page
                await page.evaluate(
                    f"""
                    document.getElementById('g-recaptcha-response').innerHTML = '{token}';
                    """
                )
                logger.info("reCAPTCHA token injected")
                return True

        except Exception as e:
            logger.error(f"Failed to solve reCAPTCHA: {e}")

        return False

    async def _solve_hcaptcha(self, page: "Page", captcha_info: CaptchaInfo) -> bool:
        """
        Solve hCaptcha using external service.

        Args:
            page: Playwright page instance
            captcha_info: CAPTCHA information

        Returns:
            True if solved successfully
        """
        if not captcha_info.site_key:
            logger.error("Cannot solve hCaptcha: site key not found")
            return False

        try:
            if self.service == "2captcha":
                token = await self._solve_2captcha_hcaptcha(
                    captcha_info.site_key,
                    captcha_info.page_url,
                )
            else:
                token = await self._solve_anticaptcha_hcaptcha(
                    captcha_info.site_key,
                    captcha_info.page_url,
                )

            if token:
                await page.evaluate(
                    f"""
                    document.querySelector('[name="h-captcha-response"]').innerHTML = '{token}';
                    document.querySelector('[name="g-recaptcha-response"]').innerHTML = '{token}';
                    """
                )
                logger.info("hCaptcha token injected")
                return True

        except Exception as e:
            logger.error(f"Failed to solve hCaptcha: {e}")

        return False

    async def _solve_2captcha_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA using 2Captcha service."""
        async with httpx.AsyncClient() as client:
            # Submit task
            response = await client.get(
                self._endpoints["2captcha"]["submit"],
                params={
                    "key": self.api_key,
                    "method": "userrecaptcha",
                    "googlekey": site_key,
                    "pageurl": page_url,
                    "json": 1,
                },
            )
            result = response.json()

            if result.get("status") != 1:
                logger.error(f"2Captcha submit error: {result.get('error_text')}")
                return None

            task_id = result["request"]
            logger.info(f"2Captcha task submitted: {task_id}")

            # Wait for result
            return await self._wait_2captcha_result(client, task_id)

    async def _solve_2captcha_hcaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve hCaptcha using 2Captcha service."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self._endpoints["2captcha"]["submit"],
                params={
                    "key": self.api_key,
                    "method": "hcaptcha",
                    "sitekey": site_key,
                    "pageurl": page_url,
                    "json": 1,
                },
            )
            result = response.json()

            if result.get("status") != 1:
                logger.error(f"2Captcha submit error: {result.get('error_text')}")
                return None

            task_id = result["request"]
            return await self._wait_2captcha_result(client, task_id)

    async def _wait_2captcha_result(self, client: httpx.AsyncClient, task_id: str) -> Optional[str]:
        """Wait for 2Captcha result."""
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < self.timeout:
            await asyncio.sleep(5)

            response = await client.get(
                self._endpoints["2captcha"]["result"],
                params={
                    "key": self.api_key,
                    "action": "get",
                    "id": task_id,
                    "json": 1,
                },
            )
            result = response.json()

            if result.get("status") == 1:
                logger.info("CAPTCHA solved successfully")
                return result["request"]

            if result.get("request") != "CAPCHA_NOT_READY":
                logger.error(f"2Captcha error: {result.get('error_text')}")
                return None

        logger.error("2Captcha timeout")
        return None

    async def _solve_anticaptcha_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA using Anti-Captcha service."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._endpoints["anticaptcha"]["submit"],
                json={
                    "clientKey": self.api_key,
                    "task": {
                        "type": "RecaptchaV2TaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": site_key,
                    },
                },
            )
            result = response.json()

            if result.get("errorId") != 0:
                logger.error(f"Anti-Captcha error: {result.get('errorDescription')}")
                return None

            task_id = result["taskId"]
            return await self._wait_anticaptcha_result(client, task_id)

    async def _solve_anticaptcha_hcaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve hCaptcha using Anti-Captcha service."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._endpoints["anticaptcha"]["submit"],
                json={
                    "clientKey": self.api_key,
                    "task": {
                        "type": "HCaptchaTaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": site_key,
                    },
                },
            )
            result = response.json()

            if result.get("errorId") != 0:
                logger.error(f"Anti-Captcha error: {result.get('errorDescription')}")
                return None

            task_id = result["taskId"]
            return await self._wait_anticaptcha_result(client, task_id)

    async def _wait_anticaptcha_result(self, client: httpx.AsyncClient, task_id: int) -> Optional[str]:
        """Wait for Anti-Captcha result."""
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < self.timeout:
            await asyncio.sleep(5)

            response = await client.post(
                self._endpoints["anticaptcha"]["result"],
                json={
                    "clientKey": self.api_key,
                    "taskId": task_id,
                },
            )
            result = response.json()

            if result.get("status") == "ready":
                logger.info("CAPTCHA solved successfully")
                return result["solution"]["gRecaptchaResponse"]

            if result.get("errorId") != 0:
                logger.error(f"Anti-Captcha error: {result.get('errorDescription')}")
                return None

        logger.error("Anti-Captcha timeout")
        return None
