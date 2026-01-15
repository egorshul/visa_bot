"""
Configuration management module.

Loads configuration from YAML file and environment variables.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv


class Config:
    """Configuration manager for the visa bot."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to config.yaml file. If not provided,
                        looks for config/config.yaml in project root.
        """
        # Load environment variables from .env file
        load_dotenv()

        # Determine config file path
        if config_path is None:
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "config.yaml"
        else:
            config_path = Path(config_path)

        # Load configuration
        self._config = self._load_config(config_path)
        self._resolve_env_vars()

    def _load_config(self, config_path: Path) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}\n"
                "Please copy config.yaml.example to config.yaml and fill in your values."
            )

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _resolve_env_vars(self) -> None:
        """Replace ${VAR} patterns with environment variable values."""
        self._config = self._resolve_dict(self._config)

    def _resolve_dict(self, obj: Any) -> Any:
        """Recursively resolve environment variables in config."""
        if isinstance(obj, dict):
            return {k: self._resolve_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_dict(item) for item in obj]
        elif isinstance(obj, str):
            return self._resolve_string(obj)
        return obj

    def _resolve_string(self, value: str) -> str:
        """Replace ${VAR} with environment variable value."""
        pattern = r"\$\{([^}]+)\}"
        matches = re.findall(pattern, value)

        for var_name in matches:
            env_value = os.getenv(var_name, "")
            value = value.replace(f"${{{var_name}}}", env_value)

        return value

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation key.

        Args:
            key: Dot-notation key (e.g., "vfs.centers")
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key.split(".")
        value = self._config

        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def __getitem__(self, key: str) -> Any:
        """Get configuration value using bracket notation."""
        value = self.get(key)
        if value is None:
            raise KeyError(f"Configuration key not found: {key}")
        return value

    @property
    def mode(self) -> str:
        """Get application mode (debug/prod)."""
        return self.get("mode", "prod")

    @property
    def is_debug(self) -> bool:
        """Check if running in debug mode."""
        return self.mode == "debug" or os.getenv("DEBUG", "0") == "1"

    # VFS Configuration
    @property
    def vfs_base_url(self) -> str:
        """Get VFS Global base URL."""
        return self.get("vfs.base_url", "https://visa.vfsglobal.com")

    @property
    def country_code(self) -> str:
        """Get country code for VFS."""
        return self.get("vfs.country_code", "rus")

    @property
    def language(self) -> str:
        """Get language setting."""
        return self.get("vfs.language", "en")

    @property
    def destination_country(self) -> str:
        """Get visa destination country."""
        return self.get("vfs.destination_country", "fra")

    @property
    def visa_type(self) -> str:
        """Get visa type."""
        return self.get("vfs.visa_type", "short_stay")

    @property
    def visa_subcategory(self) -> str:
        """Get visa subcategory."""
        return self.get("vfs.visa_subcategory", "all_other_short_stay")

    @property
    def centers(self) -> List[str]:
        """Get list of visa centers to monitor."""
        return self.get("vfs.centers", ["Moscow"])

    @property
    def applicants_count(self) -> int:
        """Get number of applicants."""
        return self.get("vfs.applicants_count", 1)

    # Account credentials
    @property
    def vfs_email(self) -> str:
        """Get VFS account email."""
        return self.get("account.email", "")

    @property
    def vfs_password(self) -> str:
        """Get VFS account password."""
        return self.get("account.password", "")

    # Schedule
    @property
    def min_interval(self) -> int:
        """Get minimum check interval in seconds."""
        return self.get("schedule.min_interval", 60)

    @property
    def max_interval(self) -> int:
        """Get maximum check interval in seconds."""
        return self.get("schedule.max_interval", 300)

    @property
    def randomize_interval(self) -> bool:
        """Check if interval randomization is enabled."""
        return self.get("schedule.randomize", True)

    # Browser settings
    @property
    def browser_headless(self) -> bool:
        """Check if browser should run in headless mode."""
        return self.get("browser.headless", False)

    @property
    def browser_slow_mo(self) -> int:
        """Get browser slow motion delay."""
        return self.get("browser.slow_mo", 50)

    @property
    def browser_type(self) -> str:
        """Get browser type."""
        return self.get("browser.type", "chromium")

    @property
    def viewport(self) -> Dict[str, int]:
        """Get viewport dimensions."""
        return self.get("browser.viewport", {"width": 1920, "height": 1080})

    @property
    def proxy_enabled(self) -> bool:
        """Check if proxy is enabled."""
        return self.get("browser.proxy.enabled", False)

    @property
    def proxy_config(self) -> Optional[Dict[str, str]]:
        """Get proxy configuration."""
        if not self.proxy_enabled:
            return None
        return {
            "server": self.get("browser.proxy.server", ""),
            "username": self.get("browser.proxy.username", ""),
            "password": self.get("browser.proxy.password", ""),
        }

    # Anti-bot settings
    @property
    def stealth_mode(self) -> bool:
        """Check if stealth mode is enabled."""
        return self.get("antibot.stealth_mode", True)

    @property
    def mouse_movements(self) -> bool:
        """Check if random mouse movements are enabled."""
        return self.get("antibot.mouse_movements", True)

    @property
    def random_scroll(self) -> bool:
        """Check if random scrolling is enabled."""
        return self.get("antibot.random_scroll", True)

    @property
    def typing_delay(self) -> Dict[str, int]:
        """Get typing delay range."""
        return self.get("antibot.typing_delay", {"min": 50, "max": 150})

    @property
    def action_delay(self) -> Dict[str, int]:
        """Get action delay range."""
        return self.get("antibot.action_delay", {"min": 500, "max": 2000})

    # CAPTCHA settings
    @property
    def captcha_auto_solve(self) -> bool:
        """Check if CAPTCHA auto-solving is enabled."""
        return self.get("captcha.auto_solve", False)

    @property
    def captcha_service(self) -> str:
        """Get CAPTCHA solving service."""
        return self.get("captcha.service", "2captcha")

    @property
    def captcha_api_key(self) -> str:
        """Get CAPTCHA service API key."""
        return self.get("captcha.api_key", "")

    @property
    def captcha_timeout(self) -> int:
        """Get CAPTCHA solving timeout."""
        return self.get("captcha.timeout", 120)

    # Telegram settings
    @property
    def telegram_enabled(self) -> bool:
        """Check if Telegram notifications are enabled."""
        return self.get("telegram.enabled", True)

    @property
    def telegram_bot_token(self) -> str:
        """Get Telegram bot token."""
        return self.get("telegram.bot_token", "")

    @property
    def telegram_chat_id(self) -> str:
        """Get Telegram chat ID."""
        return self.get("telegram.chat_id", "")

    @property
    def telegram_notify_on(self) -> Dict[str, bool]:
        """Get Telegram notification events."""
        return self.get("telegram.notify_on", {
            "slot_available": True,
            "error": True,
            "captcha": True,
            "daily_status": True,
        })

    # Email settings
    @property
    def email_enabled(self) -> bool:
        """Check if email notifications are enabled."""
        return self.get("email.enabled", False)

    @property
    def email_config(self) -> Dict[str, Any]:
        """Get email configuration."""
        return {
            "smtp_server": self.get("email.smtp_server", ""),
            "smtp_port": self.get("email.smtp_port", 587),
            "use_tls": self.get("email.use_tls", True),
            "sender_email": self.get("email.sender_email", ""),
            "sender_password": self.get("email.sender_password", ""),
            "recipient_email": self.get("email.recipient_email", ""),
        }

    # Logging settings
    @property
    def log_level(self) -> str:
        """Get log level."""
        return self.get("logging.level", "INFO")

    @property
    def log_file(self) -> str:
        """Get log file path."""
        return self.get("logging.log_file", "logs/visa_bot.log")

    @property
    def log_max_size(self) -> int:
        """Get max log file size in MB."""
        return self.get("logging.max_size", 10)

    @property
    def log_backup_count(self) -> int:
        """Get number of backup log files."""
        return self.get("logging.backup_count", 5)

    @property
    def console_logging(self) -> bool:
        """Check if console logging is enabled."""
        return self.get("logging.console_logging", True)

    # Retry settings
    @property
    def max_retries(self) -> int:
        """Get max retry attempts."""
        return self.get("retry.max_retries", 3)

    @property
    def retry_delay(self) -> int:
        """Get delay between retries in seconds."""
        return self.get("retry.retry_delay", 30)

    @property
    def auto_restart(self) -> bool:
        """Check if auto-restart is enabled."""
        return self.get("retry.auto_restart", True)

    @property
    def max_consecutive_errors(self) -> int:
        """Get max consecutive errors before pause."""
        return self.get("retry.max_consecutive_errors", 5)

    @property
    def error_pause_duration(self) -> int:
        """Get error pause duration in minutes."""
        return self.get("retry.error_pause_duration", 15)

    def get_application_url(self) -> str:
        """Generate VFS application URL."""
        return (
            f"{self.vfs_base_url}/{self.country_code}/{self.language}/"
            f"{self.destination_country}/application-detail"
        )

    def get_login_url(self) -> str:
        """Generate VFS login URL."""
        return (
            f"{self.vfs_base_url}/{self.country_code}/{self.language}/"
            f"{self.destination_country}/login"
        )

    def validate(self) -> List[str]:
        """
        Validate configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check required credentials
        if not self.vfs_email:
            errors.append("VFS email is not configured")
        if not self.vfs_password:
            errors.append("VFS password is not configured")

        # Check Telegram config if enabled
        if self.telegram_enabled:
            if not self.telegram_bot_token:
                errors.append("Telegram bot token is not configured")
            if not self.telegram_chat_id:
                errors.append("Telegram chat ID is not configured")

        # Check CAPTCHA config if auto-solve enabled
        if self.captcha_auto_solve and not self.captcha_api_key:
            errors.append("CAPTCHA API key is not configured but auto-solve is enabled")

        # Check visa centers
        if not self.centers:
            errors.append("No visa centers configured")

        return errors
