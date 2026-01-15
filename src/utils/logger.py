"""
Logging module for the visa bot.

Provides colorful console output and rotating file logging.
"""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

try:
    import colorlog

    COLORLOG_AVAILABLE = True
except ImportError:
    COLORLOG_AVAILABLE = False


# Global logger instance
_logger: Optional[logging.Logger] = None


def setup_logger(
    name: str = "visa_bot",
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_size_mb: int = 10,
    backup_count: int = 5,
    console_output: bool = True,
) -> logging.Logger:
    """
    Set up and configure the logger.

    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to log file (optional)
        max_size_mb: Max log file size in MB
        backup_count: Number of backup files to keep
        console_output: Whether to output to console

    Returns:
        Configured logger instance
    """
    global _logger

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    logger.handlers.clear()

    # Log format
    log_format = "%(asctime)s | %(levelname)-8s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Console handler with colors
    if console_output:
        if COLORLOG_AVAILABLE:
            console_handler = colorlog.StreamHandler(sys.stdout)
            console_handler.setFormatter(
                colorlog.ColoredFormatter(
                    "%(log_color)s%(asctime)s | %(levelname)-8s | %(message)s%(reset)s",
                    datefmt=date_format,
                    log_colors={
                        "DEBUG": "cyan",
                        "INFO": "green",
                        "WARNING": "yellow",
                        "ERROR": "red",
                        "CRITICAL": "red,bg_white",
                    },
                )
            )
        else:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(
                logging.Formatter(log_format, datefmt=date_format)
            )

        logger.addHandler(console_handler)

    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
        logger.addHandler(file_handler)

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """
    Get the global logger instance.

    Returns:
        Logger instance (creates default if not initialized)
    """
    global _logger

    if _logger is None:
        _logger = setup_logger()

    return _logger


class BotLogger:
    """
    Wrapper class for bot-specific logging with context.
    """

    def __init__(self, component: str):
        """
        Initialize logger wrapper.

        Args:
            component: Component name for log prefix
        """
        self.component = component
        self._logger = get_logger()

    def _format_message(self, message: str) -> str:
        """Format message with component prefix."""
        return f"[{self.component}] {message}"

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message."""
        self._logger.debug(self._format_message(message), **kwargs)

    def info(self, message: str, **kwargs) -> None:
        """Log info message."""
        self._logger.info(self._format_message(message), **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message."""
        self._logger.warning(self._format_message(message), **kwargs)

    def error(self, message: str, **kwargs) -> None:
        """Log error message."""
        self._logger.error(self._format_message(message), **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        """Log critical message."""
        self._logger.critical(self._format_message(message), **kwargs)

    def success(self, message: str) -> None:
        """Log success message (info level with marker)."""
        self._logger.info(self._format_message(f"[SUCCESS] {message}"))

    def slot_found(self, center: str, date: str, time_slot: str) -> None:
        """Log slot found event."""
        self._logger.info(
            self._format_message(
                f"[SLOT FOUND] Center: {center}, Date: {date}, Time: {time_slot}"
            )
        )

    def no_slots(self, center: str) -> None:
        """Log no slots available."""
        self._logger.info(self._format_message(f"[NO SLOTS] Center: {center}"))

    def check_started(self, center: str) -> None:
        """Log check started."""
        self._logger.info(self._format_message(f"[CHECK] Starting check for {center}"))

    def check_completed(self, duration: float) -> None:
        """Log check completed."""
        self._logger.info(
            self._format_message(f"[CHECK] Completed in {duration:.2f}s")
        )

    def waiting(self, seconds: int) -> None:
        """Log waiting period."""
        self._logger.info(
            self._format_message(f"[WAIT] Waiting {seconds}s until next check")
        )

    def exception(self, message: str, exc: Exception) -> None:
        """Log exception with traceback."""
        self._logger.exception(self._format_message(f"{message}: {exc}"))
