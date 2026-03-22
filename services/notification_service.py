import logging
import aiohttp
from datetime import datetime

logger = logging.getLogger("apex.notification_service")

class NotificationService:

    def __init__(self, config: dict):
        self.token = config.get("telegram_token", "")
        self.chat_id = config.get("telegram_chat_id", "")
        self.enabled = bool(self.token and self.chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    async def send(self, text: str):
        if not self.enabled:
            return
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
                )
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    async def trade_opened(self, position: dict):
        direction = position.get("direction", "")
        arrow = "🟢📈" if direction == "long" else "🔴📉"
        mode = position.get("mode", "simulation")
        mode_tag = "🔵 SIM" if mode == "simulation" else "⚡ LIVE"
        text = (
            f"{arrow} <b>ПОЗИЦИЯ ОТКРЫТА</b> [{mode_tag}]\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>{position.get('symbol')}</b> | {direction.upper()}\n"
            f"💰 Entry: <b>{position.get('entry')}</b>\n"
            f"🛡 SL: {position.get('sl')}\n"
            f"🎯 TP1: {position.get('tp1')} | TP2: {position.get('tp2')} | TP3: {position.get('tp3')}\n"
            f"📦 Size: {position.get('size')}\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        await self.send(text)

    async def trade_closed(self, result: dict):
        reason = result.get("close_reason", "")
        pnl = result.get("pnl_usdt", 0)
        pnl_pct = result.get("pnl_pct", 0)
        emoji = "🔴" if reason == "SL" else ("🟡" if reason in ["TP1","TP2"] else "🟢")
        mode_tag = "🔵 SIM" if result.get("mode") == "simulation" else "⚡ LIVE"
        sign = "+" if pnl >= 0 else ""
        text = (
            f"{emoji} <b>ПОЗИЦИЯ ЗАКРЫТА</b> [{mode_tag}]\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>{result.get('symbol')}</b> | {result.get('direction','').upper()}\n"
            f"🏁 Причина: <b>{reason}</b>\n"
            f"💵 PnL: <b>{sign}{pnl} USDT</b> ({sign}{pnl_pct}%)\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        await self.send(text)