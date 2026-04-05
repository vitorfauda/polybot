"""Telegram alert service for trade notifications."""

import httpx
from core.config import get_settings


class TelegramAlert:
    """Sends trade alerts and daily summaries via Telegram."""

    def __init__(self):
        settings = get_settings()
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.enabled = bool(self.token and self.chat_id)

    async def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                })
                return resp.status_code == 200
            except Exception as e:
                print(f"[Telegram] Error: {e}")
                return False

    async def notify_trade(self, trade: dict, analysis: dict | None = None) -> bool:
        direction = trade.get("direction", "?").upper()
        cost = trade.get("cost", 0)
        price = trade.get("price", 0)
        edge = trade.get("edge", 0)
        question = trade.get("question", "Unknown market")

        emoji = "🟢" if direction == "YES" else "🔴"
        msg = (
            f"{emoji} <b>New Trade Executed</b>\n\n"
            f"<b>Market:</b> {question}\n"
            f"<b>Direction:</b> {direction}\n"
            f"<b>Price:</b> {price:.2f} ({price*100:.0f}%)\n"
            f"<b>Cost:</b> ${cost:.2f}\n"
            f"<b>Edge:</b> {edge*100:.1f}%\n"
        )
        if analysis:
            reasoning = analysis.get("reasoning", "")
            confidence = analysis.get("confidence", 0)
            msg += (
                f"\n<b>AI Confidence:</b> {confidence*100:.0f}%\n"
                f"<b>Reasoning:</b> {reasoning[:200]}\n"
            )
        return await self.send(msg)

    async def notify_resolution(self, trade: dict) -> bool:
        pnl = trade.get("pnl", 0)
        question = trade.get("question", trade.get("market_id", "Unknown"))
        emoji = "✅" if pnl > 0 else "❌"
        msg = (
            f"{emoji} <b>Position Resolved</b>\n\n"
            f"<b>Market:</b> {question}\n"
            f"<b>P&L:</b> ${pnl:+.2f}\n"
            f"<b>Outcome:</b> {trade.get('outcome', '?').upper()}\n"
        )
        return await self.send(msg)

    async def notify_daily_summary(self, stats: dict) -> bool:
        msg = (
            f"📊 <b>PolyBot Daily Summary</b>\n\n"
            f"<b>Balance:</b> ${stats.get('total_balance', 0):.2f}\n"
            f"<b>P&L:</b> ${stats.get('total_pnl', 0):+.2f}\n"
            f"<b>Trades:</b> {stats.get('total_trades', 0)}\n"
            f"<b>Win Rate:</b> {stats.get('win_rate', 0):.1f}%\n"
            f"<b>W/L:</b> {stats.get('win_count', 0)}/{stats.get('loss_count', 0)}\n"
        )
        return await self.send(msg)

    async def notify_opportunity(self, opp: dict) -> bool:
        question = opp.get("question", "?")
        edge = opp.get("edge", 0)
        score = opp.get("score", 0)
        direction = opp.get("direction", "?").upper()
        msg = (
            f"🎯 <b>Opportunity Found</b>\n\n"
            f"<b>Market:</b> {question}\n"
            f"<b>Direction:</b> {direction}\n"
            f"<b>Edge:</b> {edge*100:.1f}%\n"
            f"<b>Score:</b> {score*100:.0f}/100\n"
        )
        return await self.send(msg)
