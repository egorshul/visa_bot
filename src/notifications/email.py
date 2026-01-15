"""
Email notification module.

Sends notifications via SMTP email.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

import aiosmtplib

from ..utils.logger import BotLogger

logger = BotLogger("Email")


@dataclass
class SlotInfo:
    """Information about an available slot."""

    center: str
    date: str
    time_slots: List[str]
    booking_url: str


class EmailNotifier:
    """
    Email notification sender using SMTP.
    """

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        sender_email: str,
        sender_password: str,
        recipient_email: str,
        use_tls: bool = True,
        enabled: bool = False,
    ):
        """
        Initialize email notifier.

        Args:
            smtp_server: SMTP server address
            smtp_port: SMTP server port
            sender_email: Sender email address
            sender_password: Sender email password/app password
            recipient_email: Recipient email address
            use_tls: Use TLS encryption
            enabled: Whether email notifications are enabled
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.recipient_email = recipient_email
        self.use_tls = use_tls
        self.enabled = enabled

    @classmethod
    def from_config(cls, config: Dict) -> "EmailNotifier":
        """
        Create EmailNotifier from configuration dictionary.

        Args:
            config: Email configuration dictionary

        Returns:
            EmailNotifier instance
        """
        return cls(
            smtp_server=config.get("smtp_server", ""),
            smtp_port=config.get("smtp_port", 587),
            sender_email=config.get("sender_email", ""),
            sender_password=config.get("sender_password", ""),
            recipient_email=config.get("recipient_email", ""),
            use_tls=config.get("use_tls", True),
            enabled=config.get("enabled", False),
        )

    async def _send_email(
        self,
        subject: str,
        body_html: str,
        body_text: str = "",
    ) -> bool:
        """
        Send email.

        Args:
            subject: Email subject
            body_html: HTML body content
            body_text: Plain text body content

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            logger.debug("Email notifications disabled, skipping")
            return False

        if not all([self.smtp_server, self.sender_email, self.recipient_email]):
            logger.warning("Email not configured properly")
            return False

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender_email
            msg["To"] = self.recipient_email

            # Attach plain text and HTML versions
            if body_text:
                msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

            # Send email
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_server,
                port=self.smtp_port,
                username=self.sender_email,
                password=self.sender_password,
                use_tls=self.use_tls,
                start_tls=not self.use_tls,
            )

            logger.debug("Email sent successfully")
            return True

        except aiosmtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    async def notify_slot_available(self, slot: SlotInfo) -> bool:
        """
        Send notification about available slot.

        Args:
            slot: Slot information

        Returns:
            True if sent successfully
        """
        subject = f"🎉 VFS: Свободный слот найден - {slot.center}"

        time_slots_html = "".join([f"<li>{t}</li>" for t in slot.time_slots])

        body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .header {{ background: #4CAF50; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; }}
        .info {{ background: #f9f9f9; padding: 15px; margin: 10px 0; border-left: 4px solid #4CAF50; }}
        .cta {{ background: #4CAF50; color: white; padding: 15px 30px; text-decoration: none;
                display: inline-block; margin: 20px 0; border-radius: 5px; }}
        .footer {{ font-size: 12px; color: #666; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎉 Свободный слот найден!</h1>
    </div>
    <div class="content">
        <div class="info">
            <p><strong>📍 Визовый центр:</strong> {slot.center}</p>
            <p><strong>📅 Дата:</strong> {slot.date}</p>
            <p><strong>⏰ Доступные слоты:</strong></p>
            <ul>{time_slots_html}</ul>
        </div>

        <p>⚡️ Срочно бронируйте слот!</p>

        <a href="{slot.booking_url}" class="cta">Забронировать сейчас</a>

        <div class="footer">
            <p>Это автоматическое уведомление от VFS Visa Slot Checker Bot.</p>
            <p>Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>
"""

        body_text = f"""
СВОБОДНЫЙ СЛОТ НАЙДЕН!

Визовый центр: {slot.center}
Дата: {slot.date}
Доступные слоты: {', '.join(slot.time_slots)}

Ссылка для бронирования: {slot.booking_url}

Срочно бронируйте!
"""

        logger.info(f"Sending email notification for {slot.center}")
        return await self._send_email(subject, body_html, body_text)

    async def notify_error(self, error_message: str, details: str = "") -> bool:
        """
        Send error notification.

        Args:
            error_message: Error description
            details: Additional details

        Returns:
            True if sent successfully
        """
        subject = "⚠️ VFS Bot: Ошибка"

        body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; color: #333; }}
        .error {{ background: #ffebee; padding: 15px; border-left: 4px solid #f44336; }}
    </style>
</head>
<body>
    <h2>⚠️ Ошибка в работе бота</h2>
    <div class="error">
        <p><strong>Ошибка:</strong> {error_message}</p>
        {"<p><strong>Детали:</strong> " + details + "</p>" if details else ""}
    </div>
    <p><small>Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
</body>
</html>
"""

        return await self._send_email(subject, body_html)

    async def test_connection(self) -> bool:
        """
        Test email connection.

        Returns:
            True if connection works
        """
        subject = "🔧 VFS Bot: Тестовое сообщение"
        body_html = """
<html>
<body>
    <h2>🔧 Тестовое сообщение</h2>
    <p>Email уведомления настроены корректно.</p>
</body>
</html>
"""
        return await self._send_email(subject, body_html)
