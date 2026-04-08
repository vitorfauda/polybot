"""Crypto Trading Intelligence - Specialized strategies for crypto prediction markets.

This module brings REAL crypto data into our analysis:
- CoinGecko prices and historical data
- On-chain metrics (volume, market cap, dominance)
- Crypto-specific news sentiment
- Technical indicators (momentum, volatility)
- Pattern recognition for "Will X reach $Y by Z" markets

The user's vision: Build something self-reinforcing that finds patterns in
crypto markets and analyzes EVERYTHING around the trade.
"""

import json
import re
import httpx
from datetime import datetime, timezone
from anthropic import AsyncAnthropic
from dataclasses import dataclass
from core.config import get_settings


# Common crypto symbols and their CoinGecko IDs
CRYPTO_MAP = {
    "bitcoin": "bitcoin", "btc": "bitcoin",
    "ethereum": "ethereum", "eth": "ethereum",
    "solana": "solana", "sol": "solana",
    "ripple": "ripple", "xrp": "ripple",
    "cardano": "cardano", "ada": "cardano",
    "dogecoin": "dogecoin", "doge": "dogecoin",
    "polkadot": "polkadot", "dot": "polkadot",
    "polygon": "matic-network", "matic": "matic-network",
    "avalanche": "avalanche-2", "avax": "avalanche-2",
    "chainlink": "chainlink", "link": "chainlink",
    "litecoin": "litecoin", "ltc": "litecoin",
    "binance coin": "binancecoin", "bnb": "binancecoin",
}


@dataclass
class CryptoAnalysis:
    """Complete crypto market analysis result."""
    coin: str
    current_price: float
    price_change_24h: float
    price_change_7d: float
    market_cap: float
    volume_24h: float
    rsi: float | None  # 0-100, >70 overbought, <30 oversold
    volatility: float
    target_price: float | None  # extracted from question
    target_date: str | None
    distance_to_target_pct: float | None
    momentum_score: float  # -1 to 1
    technical_signal: str  # "bullish", "bearish", "neutral"


class CryptoDataClient:
    """Fetches real crypto data from CoinGecko (free, no API key needed)."""

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=15.0)

    async def get_current_price(self, coin_id: str) -> dict | None:
        try:
            url = f"{self.BASE_URL}/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true",
            }
            resp = await self._http.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return data.get(coin_id)
        except:
            pass
        return None

    async def get_historical(self, coin_id: str, days: int = 7) -> list[float] | None:
        """Get price history for the last N days. Returns list of closing prices."""
        try:
            url = f"{self.BASE_URL}/coins/{coin_id}/market_chart"
            params = {"vs_currency": "usd", "days": days}
            resp = await self._http.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                prices = data.get("prices", [])
                return [p[1] for p in prices]
        except:
            pass
        return None

    async def close(self):
        await self._http.aclose()


def extract_target_from_question(question: str) -> tuple[str | None, float | None]:
    """
    Extract crypto coin and target price from a question.
    Examples:
    - "Will Bitcoin hit $100K by June?" -> ("bitcoin", 100000)
    - "Will ETH reach $5000 in 2026?" -> ("ethereum", 5000)
    """
    q = question.lower()

    # Find the coin
    coin_id = None
    for keyword, cid in CRYPTO_MAP.items():
        if keyword in q:
            coin_id = cid
            break
    if not coin_id:
        return None, None

    # Find target price - look for $XXX or XXXk patterns
    # Match patterns like $100K, $100,000, $100k, 100k, $5000
    patterns = [
        r'\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*([kmb])?',  # $100k, $100,000
        r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*([kmb])\b',  # 100k, 100m
    ]
    for pattern in patterns:
        match = re.search(pattern, q)
        if match:
            num_str = match.group(1).replace(',', '')
            suffix = match.group(2) or ''
            try:
                num = float(num_str)
                if suffix == 'k':
                    num *= 1000
                elif suffix == 'm':
                    num *= 1_000_000
                elif suffix == 'b':
                    num *= 1_000_000_000
                return coin_id, num
            except:
                continue

    return coin_id, None


def calculate_rsi(prices: list[float], period: int = 14) -> float | None:
    """Calculate Relative Strength Index."""
    if len(prices) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_volatility(prices: list[float]) -> float:
    """Calculate price volatility (standard deviation of % changes)."""
    if len(prices) < 2:
        return 0
    changes = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices)) if prices[i-1] > 0]
    if not changes:
        return 0
    avg = sum(changes) / len(changes)
    variance = sum((c - avg) ** 2 for c in changes) / len(changes)
    return variance ** 0.5


class CryptoIntelligence:
    """
    Specialized intelligence for crypto prediction markets.
    Combines real-time crypto data + technical analysis + Claude reasoning.
    """

    def __init__(self):
        settings = get_settings()
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None
        self.data = CryptoDataClient()

    def is_crypto_market(self, market: dict) -> bool:
        """Check if a market is about cryptocurrency."""
        question = market.get("question", "").lower()
        category = market.get("groupItemTitle", "").lower()
        if "crypto" in category:
            return True
        for keyword in CRYPTO_MAP.keys():
            if keyword in question:
                return True
        return False

    async def analyze_crypto_market(self, market: dict, news: list[dict]) -> dict:
        """
        Full crypto-specific analysis pipeline:
        1. Extract coin and target
        2. Fetch real price data
        3. Calculate technical indicators
        4. Calculate distance-to-target probability
        5. Use Claude with all this context for final verdict
        """
        question = market.get("question", "")
        coin_id, target_price = extract_target_from_question(question)

        if not coin_id:
            return {"error": "Could not identify cryptocurrency from question"}

        # Fetch current data
        current = await self.data.get_current_price(coin_id)
        if not current:
            return {"error": f"Could not fetch price for {coin_id}"}

        current_price = current.get("usd", 0)
        price_change_24h = current.get("usd_24h_change", 0)
        market_cap = current.get("usd_market_cap", 0)
        volume_24h = current.get("usd_24h_vol", 0)

        # Get historical for technical indicators
        history_7d = await self.data.get_historical(coin_id, days=7)
        history_14d = await self.data.get_historical(coin_id, days=14)

        rsi = calculate_rsi(history_14d) if history_14d else None
        volatility = calculate_volatility(history_7d) if history_7d else 0

        # 7-day price change
        price_change_7d = 0
        if history_7d and len(history_7d) > 1:
            price_change_7d = ((history_7d[-1] - history_7d[0]) / history_7d[0]) * 100

        # Distance to target analysis
        distance_pct = None
        if target_price:
            distance_pct = ((target_price - current_price) / current_price) * 100

        # Technical signal
        technical = "neutral"
        momentum = 0.0
        if rsi:
            if rsi > 70:
                technical = "overbought"
                momentum = -0.3  # likely to pull back
            elif rsi < 30:
                technical = "oversold"
                momentum = 0.3  # likely to bounce
            elif rsi > 55 and price_change_7d > 5:
                technical = "bullish"
                momentum = 0.5
            elif rsi < 45 and price_change_7d < -5:
                technical = "bearish"
                momentum = -0.5

        analysis = CryptoAnalysis(
            coin=coin_id,
            current_price=current_price,
            price_change_24h=price_change_24h,
            price_change_7d=price_change_7d,
            market_cap=market_cap,
            volume_24h=volume_24h,
            rsi=rsi,
            volatility=volatility,
            target_price=target_price,
            target_date=market.get("endDate"),
            distance_to_target_pct=distance_pct,
            momentum_score=momentum,
            technical_signal=technical,
        )

        # Now ask Claude with all this real data
        claude_verdict = await self._claude_crypto_verdict(question, analysis, news, market)

        return {
            "coin": coin_id,
            "analysis": analysis.__dict__,
            "claude_verdict": claude_verdict,
            "data_quality": "high" if (history_7d and history_14d) else "medium",
        }

    async def _claude_crypto_verdict(
        self,
        question: str,
        analysis: CryptoAnalysis,
        news: list[dict],
        market: dict,
    ) -> dict:
        """Ask Claude to make a verdict using ALL the crypto context."""
        if not self.client:
            return {"error": "No Claude API"}

        prices_raw = market.get("outcomePrices", "[0.5,0.5]")
        if isinstance(prices_raw, str):
            try:
                prices_raw = json.loads(prices_raw)
            except:
                prices_raw = [0.5, 0.5]
        market_yes = float(prices_raw[0]) if prices_raw else 0.5

        end_date = market.get("endDate", "unknown")

        # Build news context
        news_str = "\n".join([
            f"- [{a.get('sentiment_label', '?')}] {a['title']}"
            for a in news[:5]
        ]) if news else "No relevant news found."

        # Build the comprehensive prompt with REAL data
        prompt = f"""You are an expert crypto trading analyst. You have REAL market data, not guesses. Analyze this prediction market with maximum rigor.

## Market
Question: {question}
Resolves: {end_date}
Current market price: {market_yes*100:.0f}% YES

## Real-Time Data for {analysis.coin.upper()}
- Current price: ${analysis.current_price:,.2f}
- 24h change: {analysis.price_change_24h:+.2f}%
- 7d change: {analysis.price_change_7d:+.2f}%
- Market cap: ${analysis.market_cap:,.0f}
- 24h volume: ${analysis.volume_24h:,.0f}
- RSI (14): {f'{analysis.rsi:.1f}' if analysis.rsi else 'N/A'}
- 7d volatility: {analysis.volatility*100:.2f}%
- Technical signal: {analysis.technical_signal}

{(f'## Target Analysis - target ${analysis.target_price:,.0f}') if analysis.target_price else ''}
{(f'- Distance from current: {analysis.distance_to_target_pct:+.1f}%') if analysis.distance_to_target_pct is not None else ''}

## Recent Crypto News
{news_str}

## Your Analysis Framework
1. **Statistical reality**: Based on volatility, what's the probability of reaching the target in the time available?
2. **Technical setup**: Does the current chart support the move?
3. **Momentum**: Is the market going in the right direction?
4. **News catalyst**: Is there a fundamental driver?
5. **Market efficiency check**: If the market is wrong, WHY hasn't smart money already corrected it?

Be honest. Most "Will X hit $Y" markets are correctly priced. Only flag this as a trade if you see a SPECIFIC inefficiency.

Respond ONLY with JSON:
{{
    "probability": 0.XX,
    "confidence": 0.XX,
    "direction": "yes" or "no",
    "reasoning": "Specific reasoning citing the real data above",
    "key_signal": "the strongest data point supporting your view",
    "risk": "the strongest counter-argument",
    "trade_recommendation": "STRONG_BUY" or "BUY" or "HOLD" or "SKIP"
}}"""

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except Exception as e:
            return {"error": str(e)}

    async def close(self):
        await self.data.close()
