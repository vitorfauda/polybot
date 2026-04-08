"""Trading Profiles - 3 risk levels for performance comparison.

After conversation: User wants to test 3 distinct profiles operating in parallel
to find the sweet spot between trade frequency and accuracy.

- HUNTER: Ultra-strict (current 90%+ target). Few trades, max precision.
- SNIPER: Medium strictness. Some trades per cycle.
- SCOUT: Aggressive. MANY trades. Validates that the scoring works at scale.
"""

from dataclasses import dataclass


@dataclass
class TradingProfile:
    name: str
    display_name: str
    description: str
    # Edge thresholds
    min_edge: float
    min_score: float
    # Claude AI requirements
    min_claude_confidence: float
    required_verdict: list[str]
    require_pass_consensus: bool
    # Market filters
    min_volume: float
    min_liquidity: float
    max_hours_to_expiry: float
    min_hours_to_expiry: float
    # News requirements
    min_news_count: int
    require_sentiment_alignment: bool
    # Sizing
    bet_size_usd: float
    max_trades_per_scan: int
    # Extreme price filter
    avoid_extreme_prices: bool
    extreme_price_threshold: float
    # Strategy consensus required
    min_strategies_agreeing: int = 2


# ════════════════════════════════════════════════════════════════
# HUNTER === Ultra-conservador (mantém perfil atual)
# Target: 90%+ win rate. Trades raros mas certeiros.
# ════════════════════════════════════════════════════════════════
HUNTER = TradingProfile(
    name="hunter",
    display_name="Hunter (Conservador)",
    description="Caçador: Ultra-strict. Só executa quando TODOS os sinais alinham. Poucos trades, máxima assertividade.",
    min_edge=0.10,
    min_score=0.40,
    min_claude_confidence=0.75,
    required_verdict=["STRONG_BUY"],
    require_pass_consensus=True,
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
    min_strategies_agreeing=3,
)


# ════════════════════════════════════════════════════════════════
# SNIPER === Médio rigor
# Balanço entre frequência e precisão. Aceita BUY também.
# ════════════════════════════════════════════════════════════════
SNIPER = TradingProfile(
    name="sniper",
    display_name="Sniper (Médio)",
    description="Atirador: Rigor médio. Aceita BUY e STRONG_BUY. Filtros relaxados mas Claude precisa concordar.",
    min_edge=0.04,
    min_score=0.20,
    min_claude_confidence=0.55,
    required_verdict=["STRONG_BUY", "BUY", "HOLD"],
    require_pass_consensus=False,
    min_volume=100,
    min_liquidity=50,
    max_hours_to_expiry=48,
    min_hours_to_expiry=1,
    min_news_count=1,
    require_sentiment_alignment=False,
    bet_size_usd=10.0,
    max_trades_per_scan=3,
    avoid_extreme_prices=True,
    extreme_price_threshold=0.02,
    min_strategies_agreeing=1,
)


# ════════════════════════════════════════════════════════════════
# SCOUT === AGRESSIVO (vários trades)
# Filtros mínimos. Quer testar volume de trades.
# ════════════════════════════════════════════════════════════════
SCOUT = TradingProfile(
    name="scout",
    display_name="Scout (Agressivo)",
    description="Batedor: AGRESSIVO. Filtros mínimos. Aceita qualquer sinal positivo. Muitos trades para testar volume.",
    min_edge=0.01,
    min_score=0.10,
    min_claude_confidence=0.40,
    required_verdict=["STRONG_BUY", "BUY", "HOLD"],
    require_pass_consensus=False,
    min_volume=10,
    min_liquidity=10,
    max_hours_to_expiry=72,
    min_hours_to_expiry=1,
    min_news_count=0,
    require_sentiment_alignment=False,
    bet_size_usd=5.0,
    max_trades_per_scan=10,
    avoid_extreme_prices=True,
    extreme_price_threshold=0.01,
    min_strategies_agreeing=1,
)


# ════════════════════════════════════════════════════════════════
# CRYPTO HUNTER === Especialista crypto
# ════════════════════════════════════════════════════════════════
CRYPTO_HUNTER = TradingProfile(
    name="crypto_hunter",
    display_name="Crypto Hunter",
    description="Caçador Crypto: Especialista em cripto. Usa preços reais, RSI, microestrutura.",
    min_edge=0.05,
    min_score=0.20,
    min_claude_confidence=0.60,
    required_verdict=["STRONG_BUY", "BUY"],
    require_pass_consensus=False,
    min_volume=100,
    min_liquidity=50,
    max_hours_to_expiry=168,
    min_hours_to_expiry=1,
    min_news_count=0,
    require_sentiment_alignment=False,
    bet_size_usd=10.0,
    max_trades_per_scan=2,
    avoid_extreme_prices=True,
    extreme_price_threshold=0.03,
    min_strategies_agreeing=1,
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
