"""
APEX PROTOCOL™ — Telegram Notifier
Push-уведомления в Telegram от торгового пайплайна.
"""

import os
import logging
from datetime import datetime
from telegram import Bot

logger = logging.getLogger("apex.telegram_notifier")

# Модульный синглтон
_notifier: "TelegramNotifier | None" = None


def get_notifier() -> "TelegramNotifier | None":
    """Возвращает синглтон TelegramNotifier или None если токен не задан."""
    global _notifier
    if _notifier is None:
        token   = os.getenv("TELEGRAM_BOT_TOKEN")   or os.getenv("APPS_SYSTEM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")      or os.getenv("APPS_SYSTEM_BOT_CHAT_ID")
        if token and chat_id:
            _notifier = TelegramNotifier(token, int(chat_id))
        else:
            logger.warning("TelegramNotifier: токен или chat_id не найдены в окружении")
    return _notifier


class TelegramNotifier:

    def __init__(self, token: str, chat_id: int):
        self.token   = token
        self.chat_id = chat_id

    async def send(self, text: str) -> None:
        """Отправка сообщения через Bot API."""
        try:
            async with Bot(token=self.token) as bot:
                await bot.send_message(chat_id=self.chat_id, text=text)
        except Exception as e:
            logger.warning(f"TelegramNotifier.send error: {e}")

    async def notify_open(self, position: dict) -> None:
        """Уведомление об открытии сделки."""
        symbol    = position.get("symbol", "?")
        direction = position.get("direction", "long").upper()
        entry     = position.get("entry", 0)
        sl        = position.get("sl", 0)
        tp1       = position.get("tp1", 0)
        tp2       = position.get("tp2", 0)
        tp3       = position.get("tp3", 0)
        size_usdt = position.get("risk_usdt") or round(position.get("size", 0) * entry, 2)
        sl_pct    = abs(entry - sl) / entry * 100 if entry else 0

        text = (
            f"⚡ ОТКРЫТА СДЕЛКА\n"
            f"📌 {symbol} | {direction}\n"
            f"📥 Entry: {entry}\n"
            f"🛡 SL: {sl} (-{sl_pct:.1f}%)\n"
            f"🎯 TP1: {tp1} | TP2: {tp2} | TP3: {tp3}\n"
            f"💰 Размер: ${size_usdt}"
        )
        await self.send(text)

    async def notify_close(self, result: dict) -> None:
        """Уведомление о закрытии сделки."""
        symbol       = result.get("symbol", "?")
        direction    = result.get("direction", "long").upper()
        close_reason = result.get("close_reason", "?")
        pnl_usdt     = result.get("pnl_usdt", 0)

        duration = "?"
        opened_at_str    = result.get("opened_at")
        finalized_at_str = result.get("finalized_at")
        if opened_at_str and finalized_at_str:
            try:
                opened_dt    = datetime.fromisoformat(opened_at_str)
                finalized_dt = datetime.fromisoformat(finalized_at_str)
                duration = int((finalized_dt - opened_dt).total_seconds() / 60)
            except Exception:
                pass

        text = (
            f"🔒 ЗАКРЫТА СДЕЛКА\n"
            f"📌 {symbol} | {direction}\n"
            f"📤 Закрыто по: {close_reason}\n"
            f"💵 PnL: {pnl_usdt:+.2f} USDT\n"
            f"⏱ Время: {duration} мин"
        )
        await self.send(text)

    async def notify_cycle(self, stats: dict) -> None:
        """Итог цикла пайплайна."""
        signals = stats.get("signals", 0)
        opened  = stats.get("opened", 0)
        closed  = stats.get("closed", 0)
        pnl     = stats.get("pnl", 0.0)

        text = (
            f"📊 ИТОГ ЦИКЛА\n"
            f"🔍 Сигналов: {signals}\n"
            f"📂 Открыто: {opened}\n"
            f"✅ Закрыто: {closed}\n"
            f"💰 PnL цикла: {pnl:+.2f} USDT"
        )
        await self.send(text)
