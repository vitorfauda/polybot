"""Trading Profiles - 3 different strategies all targeting 90%+ accuracy.

The goal is NOT to compare risk levels - it's to compare DIFFERENT METHODOLOGIES
for finding ultra-high-confidence trades.
"""

from dataclasses import dataclass


@dataclass
class TradingProfile:
    name: str
    display_name: str
    description: str
    # Edge thresholds
    min_edge: float
    # Score thresholds (composite score)
    min_score: float
    # Claude AI requirements
    min_claude_confidence: float
    required_verdict: list[str]  # acceptable Claude verdicts
    require_pass_consensus: bool  # all 3 passes must agree on direction
    # Market filters
    min_volume: float  # minimum market volume in USD
    min_liquidity: float  # minimum order book liquidity
    max_hours_to_expiry: float
    min_hours_to_expiry: float
    # News requirements
    min_news_count: int  # minimum news articles found
    require_sentiment_alignment: bool  # news sentiment must agree with direction
    # Sizing
    bet_size_usd: float
    max_trades_per_scan: int
    # Avoid markets where price is at extremes (likely already correct)
    avoid_extreme_prices: bool
    extreme_price_threshold: float
    # Strategy consensus required
    min_strategies_agreeing: int = 2  # min independent strategies that must agree


# === HUNTER === Ultra-strict, trades very rarely, only the surest bets
HUNTER = TradingProfile(
    name="hunter",
    display_name="Hunter",
    description="Caçador: Ultra-strict filters. Only trades when ALL signals align perfectly. Few trades, max accuracy.",
    min_edge=0.12,  # need 12%+ edge
    min_score=0.45,
    min_claude_confidence=0.75,  # Claude must be 75%+ confident
    required_verdict=["STRONG_BUY"],  # only the strongest signal
    require_pass_consensus=True,  # all 3 Claude passes must agree
    min_volume=500,
    min_liquidity=200,
    max_hours_to_expiry=36,
    min_hours_to_expiry=1,
    min_news_count=2,
    require_sentiment_alignment=True,
    bet_size_usd=10.0,
    max_trades_per_scan=1,
    avoid_extreme_prices=True,
    extreme_price_threshold=0.05,
    min_strategies_agreeing=3,  # need 3 of 4 strategies agreeing
)

# === SNIPER === Balanced precision, trades selectively but more often than Hunter
SNIPER = TradingProfile(
    name="sniper",
    display_name="Sniper",
    description="Atirador: Multi-signal validation. Requires Claude AI + news + market consensus. Balanced precision.",
    min_edge=0.08,  # 8%+ edge
    min_score=0.35,
    min_claude_confidence=0.65,
    required_verdict=["STRONG_BUY", "BUY"],
    require_pass_consensus=True,
    min_volume=200,
    min_liquidity=100,
    max_hours_to_expiry=36,
    min_hours_to_expiry=1,
    min_news_count=1,
    require_sentiment_alignment=True,
    bet_size_usd=10.0,
    max_trades_per_scan=2,
    avoid_extreme_prices=True,
    extreme_price_threshold=0.03,
    min_strategies_agreeing=2,  # need 2 of 4 strategies agreeing
)

# === SCOUT === Hunts for inefficiencies via volume, takes more trades but still strict
SCOUT = TradingProfile(
    name="scout",
    display_name="Scout",
    description="Batedor: Hunts price inefficiencies. Lower edge bar but requires strong AI signal + low extreme prices.",
    min_edge=0.06,
    min_score=0.30,
    min_claude_confidence=0.60,
    required_verdict=["STRONG_BUY", "BUY"],
    require_pass_consensus=False,  # allows some pass disagreement
    min_volume=50,
    min_liquidity=50,
    max_hours_to_expiry=36,
    min_hours_to_expiry=1,
    min_news_count=0,
    require_sentiment_alignment=False,  # doesn't require sentiment match
    bet_size_usd=5.0,
    max_trades_per_scan=3,
    avoid_extreme_prices=True,
    extreme_price_threshold=0.02,
    min_strategies_agreeing=2,  # need 2 of 4 strategies (relaxed)
)


# === CRYPTO HUNTER === Specialized for cryptocurrency markets only
CRYPTO_HUNTER = TradingProfile(
    name="crypto_hunter",
    display_name="Crypto Hunter",
    description="Caçador Crypto: Especialista em mercados de cripto. Usa preços reais, RSI, volatilidade e analise tecnica.",
    min_edge=0.08,
    min_score=0.30,
    min_claude_confidence=0.65,
    required_verdict=["STRONG_BUY", "BUY"],
    require_pass_consensus=False,  # crypto strategy is its own consensus
    min_volume=100,
    min_liquidity=50,
    max_hours_to_expiry=168,  # crypto often has longer windows
    min_hours_to_expiry=1,
    min_news_count=0,
    require_sentiment_alignment=False,
    bet_size_usd=10.0,
    max_trades_per_scan=2,
    avoid_extreme_prices=True,
    extreme_price_threshold=0.03,
    min_strategies_agreeing=1,  # crypto strategy is the primary signal
)


PROFILES = {
    "hunter": HUNTER,
    "sniper": SNIPER,
    "scout": SCOUT,
    "crypto_hunter": CRYPTO_HUNTER,
}


def get_profile(name: str) -> TradingProfile | None:
    return PROFILES.get(name.lower())


def all_profiles() -> list[TradingProfile]:
    return [HUNTER, SNIPER, SCOUT, CRYPTO_HUNTER]
