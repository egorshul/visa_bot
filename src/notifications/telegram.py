"""
Telegram notification module.

Sends notifications via Telegram bot.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import httpx

from ..utils.logger import BotLogger

logger = BotLogger("Telegram")


@dataclass
class SlotInfo:
    """Information about an available slot."""

    center: str
    date: str
    time_slots: List[str]
    booking_url: str


class TelegramNotifier:
    """
    Telegram notification sender.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
        notify_on: dict = None,
    ):
        """
        Initialize Telegram notifier.

        Args:
            bot_token: Telegram bot token
            chat_id: Chat ID to send messages to
            enabled: Whether notifications are enabled
            notify_on: Dict of events to notify on
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self.notify_on = notify_on or {
            "slot_available": True,
            "error": True,
            "captcha": True,
            "daily_status": True,
        }

        self._api_base = f"https://api.telegram.org/bot{bot_token}"
        self._last_daily_status: Optional[datetime] = None

    async def _send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
    ) -> bool:
        """
        Send message to Telegram.

        Args:
            text: Message text
            parse_mode: Parse mode (HTML or Markdown)
            disable_notification: Silent notification

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            logger.debug("Telegram notifications disabled, skipping")
            return False

        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram not configured properly")
            return False

        url = f"{self._api_base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=30)
                response.raise_for_status()

                result = response.json()
                if result.get("ok"):
                    logger.debug("Telegram message sent successfully")
                    return True
                else:
                    logger.error(f"Telegram API error: {result.get('description')}")
                    return False

        except httpx.TimeoutException:
            logger.error("Telegram request timed out")
            return False
        except httpx.HTTPStatusError as e:
            logger.error(f"Telegram HTTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def notify_slot_available(self, slot: SlotInfo) -> bool:
        """
        Send notification about available slot.

        Args:
            slot: Slot information

        Returns:
            True if sent successfully
        """
        if not self.notify_on.get("slot_available", True):
            return False

        time_slots_str = "\n".join([f"  • {t}" for t in slot.time_slots])

        message = f"""
🎉 <b>СВОБОДНЫЙ СЛОТ НАЙДЕН!</b>

📍 <b>Визовый центр:</b> {slot.center}
📅 <b>Дата:</b> {slot.date}

⏰ <b>Доступные слоты:</b>
{time_slots_str}

🔗 <b>Ссылка для записи:</b>
{slot.booking_url}

⚡️ <i>Срочно бронируйте!</i>
"""

        logger.info(f"Sending slot notification for {slot.center}")
        return await self._send_message(message.strip())

    async def notify_error(self, error_message: str, details: str = "") -> bool:
        """
        Send error notification.

        Args:
            error_message: Error description
            details: Additional details

        Returns:
            True if sent successfully
        """
        if not self.notify_on.get("error", True):
            return False

        message = f"""
⚠️ <b>ОШИБКА</b>

❌ {error_message}
"""

        if details:
            message += f"\n📝 <i>Детали:</i> {details}"

        message += f"\n\n🕐 <i>Время:</i> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        return await self._send_message(message.strip(), disable_notification=True)

    async def notify_captcha(self, url: str) -> bool:
        """
        Send notification about CAPTCHA.

        Args:
            url: Page URL where CAPTCHA appeared

        Returns:
            True if sent successfully
        """
        if not self.notify_on.get("captcha", True):
            return False

        message = f"""
🔐 <b>CAPTCHA DETECTED</b>

Обнаружена CAPTCHA на странице.
Автоматическое решение недоступно.

🔗 <b>URL:</b> {url}

<i>Бот приостановлен. Пожалуйста, решите CAPTCHA вручную или дождитесь повторной попытки.</i>
"""

        return await self._send_message(message.strip())

    async def notify_status(self, checks_count: int, errors_count: int, last_check: datetime) -> bool:
        """
        Send daily status notification.

        Args:
            checks_count: Total checks performed
            errors_count: Total errors encountered
            last_check: Time of last check

        Returns:
            True if sent successfully
        """
        if not self.notify_on.get("daily_status", True):
            return False

        # Only send once per day
        now = datetime.now()
        if self._last_daily_status:
            if (now - self._last_daily_status).days < 1:
                return False

        self._last_daily_status = now

        message = f"""
📊 <b>СТАТУС БОТА</b>

✅ Бот работает в штатном режиме

📈 <b>Статистика:</b>
• Проверок выполнено: {checks_count}
• Ошибок: {errors_count}
• Последняя проверка: {last_check.strftime('%H:%M:%S')}

🕐 <i>Отчёт от:</i> {now.strftime('%Y-%m-%d %H:%M:%S')}
"""

        return await self._send_message(message.strip(), disable_notification=True)

    async def notify_started(self, centers: List[str]) -> bool:
        """
        Send notification that bot has started.

        Args:
            centers: List of monitored centers

        Returns:
            True if sent successfully
        """
        centers_str = "\n".join([f"  • {c}" for c in centers])

        message = f"""
🚀 <b>БОТ ЗАПУЩЕН</b>

Мониторинг слотов начат.

📍 <b>Визовые центры:</b>
{centers_str}

<i>Вы получите уведомление при появлении свободного слота.</i>
"""

        return await self._send_message(message.strip())

    async def notify_stopped(self, reason: str = "Manual stop") -> bool:
        """
        Send notification that bot has stopped.

        Args:
            reason: Reason for stopping

        Returns:
            True if sent successfully
        """
        message = f"""
🛑 <b>БОТ ОСТАНОВЛЕН</b>

Причина: {reason}

🕐 <i>Время:</i> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        return await self._send_message(message.strip())

    async def notify_no_slots_check(self, center: str) -> bool:
        """
        Send periodic notification that no slots were found (optional, disabled by default).

        Args:
            center: Center name

        Returns:
            True if sent successfully
        """
        # This is disabled by default to avoid spam
        return False

    async def test_connection(self) -> bool:
        """
        Test Telegram connection by sending a test message.

        Returns:
            True if connection works
        """
        message = "🔧 <b>Тестовое сообщение</b>\n\nПодключение к Telegram работает!"
        return await self._send_message(message)
