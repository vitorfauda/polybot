"""Trading Strategies - Specialized analysis frameworks for different market types.

Each strategy provides INDEPENDENT validation. We only trade when multiple
strategies agree, dramatically increasing accuracy.

The user's insight: Polymarket prices are just noise. Our edge comes from
applying real analytical frameworks the market hasn't priced in yet.
"""

import json
import re
import httpx
import feedparser
from anthropic import AsyncAnthropic
from dataclasses import dataclass
from core.config import get_settings


@dataclass
class StrategySignal:
    """Output from a strategy - whether it sees an opportunity and why."""
    strategy_name: str
    has_signal: bool
    direction: str  # "yes" or "no"
    confidence: float  # 0-1
    reasoning: str
    score: float  # how strong the signal is


class BaseStrategy:
    """Base class for all strategies."""

    name = "base"

    async def analyze(self, market: dict, news: list[dict], **kwargs) -> StrategySignal:
        raise NotImplementedError

    def applies_to(self, market: dict) -> bool:
        """Whether this strategy applies to the given market."""
        return True


# ================================================================
# STRATEGY 1: Whale Watcher - follows large traders on Polymarket
# ================================================================
class WhaleWatcherStrategy(BaseStrategy):
    """
    Looks at recent trades on the market itself. If whales are buying YES,
    that's a signal. Smart money usually has information.
    """
    name = "whale_watcher"

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=10.0)

    async def analyze(self, market: dict, news: list[dict], **kwargs) -> StrategySignal:
        condition_id = market.get("conditionId", market.get("id", ""))
        if not condition_id:
            return StrategySignal(self.name, False, "yes", 0, "No market id", 0)

        try:
            # Get recent trades from Polymarket Data API
            url = f"https://data-api.polymarket.com/trades?market={condition_id}&limit=50"
            resp = await self._http.get(url)
            trades = resp.json() if resp.status_code == 200 else []
        except:
            trades = []

        if not trades or len(trades) < 5:
            return StrategySignal(self.name, False, "yes", 0, "Insufficient trade data", 0)

        # Aggregate by side
        yes_volume = 0
        no_volume = 0
        whale_yes = 0  # large trades buying YES
        whale_no = 0

        for t in trades:
            try:
                size = float(t.get("size", 0))
                price = float(t.get("price", 0))
                side = t.get("side", "").lower()
                outcome = t.get("outcome", "")
                value_usd = size * price

                if outcome == "YES" or "yes" in str(outcome).lower():
                    if side == "buy":
                        yes_volume += value_usd
                        if value_usd > 100:  # whale = $100+ trade
                            whale_yes += 1
                elif outcome == "NO" or "no" in str(outcome).lower():
                    if side == "buy":
                        no_volume += value_usd
                        if value_usd > 100:
                            whale_no += 1
            except:
                continue

        total_volume = yes_volume + no_volume
        if total_volume < 50:
            return StrategySignal(self.name, False, "yes", 0, "Low volume", 0)

        yes_ratio = yes_volume / total_volume
        whale_score = abs(whale_yes - whale_no) / max(whale_yes + whale_no, 1)

        # Strong directional signal: 70%+ of volume on one side AND whale activity
        if yes_ratio > 0.7 and whale_yes > whale_no:
            return StrategySignal(
                self.name, True, "yes",
                confidence=min(0.85, yes_ratio),
                reasoning=f"Whales buying YES: ${yes_volume:.0f} ({yes_ratio:.0%}) vs ${no_volume:.0f}. {whale_yes} whale trades.",
                score=yes_ratio * (0.5 + whale_score * 0.5),
            )
        elif yes_ratio < 0.3 and whale_no > whale_yes:
            return StrategySignal(
                self.name, True, "no",
                confidence=min(0.85, 1 - yes_ratio),
                reasoning=f"Whales buying NO: ${no_volume:.0f} ({(1-yes_ratio):.0%}) vs ${yes_volume:.0f}. {whale_no} whale trades.",
                score=(1 - yes_ratio) * (0.5 + whale_score * 0.5),
            )

        return StrategySignal(
            self.name, False, "yes", 0.3,
            f"Mixed signal: YES {yes_ratio:.0%} / NO {(1-yes_ratio):.0%}", 0,
        )

    async def close(self):
        await self._http.aclose()


# ================================================================
# STRATEGY 2: News Momentum - strong news bias
# ================================================================
class NewsMomentumStrategy(BaseStrategy):
    """
    If multiple news articles strongly favor one direction with consistent sentiment,
    this is a momentum signal. Requires high consensus among articles.
    """
    name = "news_momentum"

    async def analyze(self, market: dict, news: list[dict], **kwargs) -> StrategySignal:
        if len(news) < 3:
            return StrategySignal(self.name, False, "yes", 0, "Not enough news", 0)

        sentiments = [a.get("sentiment_vader", 0) for a in news]
        avg = sum(sentiments) / len(sentiments)

        # Count strong-direction articles
        strong_pos = sum(1 for s in sentiments if s > 0.3)
        strong_neg = sum(1 for s in sentiments if s < -0.3)
        neutral = sum(1 for s in sentiments if -0.05 <= s <= 0.05)

        # Need at least 60% directional consensus
        total = len(sentiments)
        pos_ratio = strong_pos / total
        neg_ratio = strong_neg / total

        if pos_ratio >= 0.6 and avg > 0.25:
            return StrategySignal(
                self.name, True, "yes",
                confidence=min(0.85, pos_ratio + 0.1),
                reasoning=f"News momentum POSITIVE: {strong_pos}/{total} bullish articles, avg sentiment {avg:+.2f}",
                score=pos_ratio,
            )
        elif neg_ratio >= 0.6 and avg < -0.25:
            return StrategySignal(
                self.name, True, "no",
                confidence=min(0.85, neg_ratio + 0.1),
                reasoning=f"News momentum NEGATIVE: {strong_neg}/{total} bearish articles, avg sentiment {avg:+.2f}",
                score=neg_ratio,
            )

        return StrategySignal(
            self.name, False, "yes", 0.2,
            f"No news consensus: {strong_pos} pos / {strong_neg} neg / {neutral} neutral", 0,
        )


# ================================================================
# STRATEGY 3: Time Decay - use time-pressure as signal
# ================================================================
class TimeDecayStrategy(BaseStrategy):
    """
    For binary events with low YES probability:
    - If event hasn't happened yet AND time is running out AND no signal of imminent event,
      then NO becomes more likely.
    Conversely if YES is very low and event is days away, NO is even safer.
    """
    name = "time_decay"

    async def analyze(self, market: dict, news: list[dict], **kwargs) -> StrategySignal:
        from dateutil import parser as date_parser
        from datetime import datetime, timezone

        end_date_str = market.get("endDate")
        if not end_date_str:
            return StrategySignal(self.name, False, "yes", 0, "No end date", 0)

        try:
            end_date = date_parser.parse(end_date_str)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            hours_left = (end_date - datetime.now(timezone.utc)).total_seconds() / 3600
        except:
            return StrategySignal(self.name, False, "yes", 0, "Bad date", 0)

        prices = market.get("outcomePrices", "[0.5,0.5]")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except:
                return StrategySignal(self.name, False, "yes", 0, "Bad prices", 0)

        price_yes = float(prices[0]) if prices else 0.5

        # Strategy: If YES is below 15% AND less than 12 hours remain AND no major news,
        # NO is very likely correct (the unlikely event probably won't happen)
        recent_news = sum(1 for a in news if "today" in a.get("title", "").lower() or "now" in a.get("title", "").lower())

        if price_yes <= 0.15 and hours_left <= 12 and recent_news == 0:
            return StrategySignal(
                self.name, True, "no",
                confidence=0.80,
                reasoning=f"Low-prob event ({price_yes*100:.0f}%) with {hours_left:.1f}h left, no breaking news suggests NO",
                score=0.7,
            )

        # Conversely: HIGH probability with little time = YES likely correct
        if price_yes >= 0.85 and hours_left <= 12 and recent_news == 0:
            return StrategySignal(
                self.name, True, "yes",
                confidence=0.80,
                reasoning=f"High-prob event ({price_yes*100:.0f}%) with {hours_left:.1f}h left, no contradicting news",
                score=0.7,
            )

        return StrategySignal(self.name, False, "yes", 0.3, "No time-decay opportunity", 0)


# ================================================================
# STRATEGY 4: AI Domain Expert - Claude as specialized analyst
# ================================================================
class AIDomainExpertStrategy(BaseStrategy):
    """
    Detects market category and asks Claude to act as a domain expert.
    Different categories get different framing prompts.
    """
    name = "ai_domain_expert"

    def __init__(self):
        settings = get_settings()
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None

    def _detect_category(self, question: str) -> str:
        q = question.lower()
        if any(w in q for w in ["nfl", "nba", "fifa", "uefa", "champions league", "world cup", "premier league", "soccer", "football", "tennis", "ufc", "f1", "formula 1"]):
            return "sports"
        if any(w in q for w in ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "binance"]):
            return "crypto"
        if any(w in q for w in ["election", "president", "trump", "biden", "congress", "senate", "vote", "polls"]):
            return "politics"
        if any(w in q for w in ["fed", "inflation", "interest rate", "recession", "gdp", "unemployment"]):
            return "economics"
        if any(w in q for w in ["movie", "netflix", "oscar", "grammy", "billboard", "celebrity"]):
            return "culture"
        return "general"

    def _expert_prompt(self, category: str, question: str, news: list[dict]) -> str:
        news_str = "\n".join([f"- {a['title']}" for a in news[:5]])

        category_framings = {
            "sports": "You are a professional sports analyst with expertise in statistics, team form, and historical data.",
            "crypto": "You are a crypto market analyst with expertise in on-chain data, technical analysis, and macro trends.",
            "politics": "You are a political analyst with expertise in polling, electoral history, and political dynamics.",
            "economics": "You are a macroeconomist with expertise in central bank policy, market data, and economic indicators.",
            "culture": "You are a cultural/entertainment analyst tracking trends, audience data, and industry signals.",
            "general": "You are a generalist analyst skilled at probabilistic reasoning and base rates.",
        }
        framing = category_framings.get(category, category_framings["general"])

        return f"""{framing}

Question: {question}

Recent news:
{news_str}

As a domain expert, give your independent probability estimate. Don't consider what the market thinks - just your professional analysis.

Consider:
1. Base rates - how often does this type of event happen historically?
2. Specific factors unique to this case
3. Strongest argument FOR yes
4. Strongest argument AGAINST yes
5. Your final probability with confidence level

Respond ONLY with JSON:
{{"probability": 0.XX, "confidence": 0.XX, "direction": "yes"/"no", "reasoning": "1-2 sentence expert verdict", "category": "{category}"}}"""

    async def analyze(self, market: dict, news: list[dict], **kwargs) -> StrategySignal:
        if not self.client:
            return StrategySignal(self.name, False, "yes", 0, "No Claude API", 0)

        question = market.get("question", "")
        category = self._detect_category(question)
        prompt = self._expert_prompt(category, question, news)

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            result = json.loads(text)

            prob = float(result.get("probability", 0.5))
            conf = float(result.get("confidence", 0.5))
            direction = result.get("direction", "yes")

            # Compare to market price for edge
            prices = market.get("outcomePrices", "[0.5,0.5]")
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except:
                    prices = [0.5, 0.5]
            market_yes = float(prices[0]) if prices else 0.5

            edge = prob - market_yes if direction == "yes" else (1 - prob) - (1 - market_yes)
            has_signal = abs(edge) > 0.05 and conf >= 0.6

            return StrategySignal(
                self.name, has_signal, direction,
                confidence=conf,
                reasoning=f"[{category.upper()}] {result.get('reasoning', '')[:200]}",
                score=conf * abs(edge) * 5,  # scale up
            )
        except Exception as e:
            return StrategySignal(self.name, False, "yes", 0, f"Error: {e}", 0)


# ================================================================
# Strategy Orchestrator
# ================================================================
class StrategyOrchestrator:
    """
    Runs multiple strategies and combines their signals.
    Only triggers a trade when MULTIPLE strategies agree.
    """

    def __init__(self):
        self.strategies = [
            AIDomainExpertStrategy(),
            NewsMomentumStrategy(),
            WhaleWatcherStrategy(),
            TimeDecayStrategy(),
        ]

    async def evaluate(
        self,
        market: dict,
        news: list[dict],
        min_agreeing: int = 2,
    ) -> dict:
        """
        Run all strategies and return consolidated decision.

        Returns:
            {
                "should_trade": bool,
                "direction": "yes"|"no",
                "confidence": float,
                "agreeing_strategies": int,
                "signals": list[StrategySignal],
                "consensus_reasoning": str,
            }
        """
        signals = []
        for strategy in self.strategies:
            try:
                signal = await strategy.analyze(market, news)
                signals.append(signal)
            except Exception as e:
                print(f"[{strategy.name}] Error: {e}")
                continue

        active = [s for s in signals if s.has_signal]
        yes_signals = [s for s in active if s.direction == "yes"]
        no_signals = [s for s in active if s.direction == "no"]

        # Determine winning direction
        if len(yes_signals) > len(no_signals) and len(yes_signals) >= min_agreeing:
            direction = "yes"
            agreeing = yes_signals
        elif len(no_signals) > len(yes_signals) and len(no_signals) >= min_agreeing:
            direction = "no"
            agreeing = no_signals
        else:
            return {
                "should_trade": False,
                "direction": "yes",
                "confidence": 0,
                "agreeing_strategies": max(len(yes_signals), len(no_signals)),
                "signals": signals,
                "consensus_reasoning": f"No consensus: {len(yes_signals)} YES vs {len(no_signals)} NO signals (need {min_agreeing}+)",
            }

        avg_confidence = sum(s.confidence for s in agreeing) / len(agreeing)
        consensus = " | ".join([f"[{s.strategy_name}] {s.reasoning[:80]}" for s in agreeing])

        return {
            "should_trade": True,
            "direction": direction,
            "confidence": avg_confidence,
            "agreeing_strategies": len(agreeing),
            "signals": signals,
            "consensus_reasoning": consensus,
        }

    async def close(self):
        for s in self.strategies:
            if hasattr(s, "close"):
                try:
                    await s.close()
                except:
                    pass
