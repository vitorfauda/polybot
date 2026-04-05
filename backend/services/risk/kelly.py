"""Kelly Criterion position sizing with fractional Kelly for risk management."""

from dataclasses import dataclass


@dataclass
class PositionSize:
    kelly_full: float  # full Kelly fraction
    kelly_fraction: float  # fractional Kelly (what we actually use)
    bet_size_usd: float  # dollar amount to bet
    expected_value: float  # expected value of the bet
    risk_reward_ratio: float


class KellySizer:
    """Fractional Kelly Criterion for optimal position sizing."""

    def __init__(self, fraction: float = 0.25, max_position_pct: float = 0.05):
        self.fraction = fraction  # use 1/4 Kelly by default
        self.max_position_pct = max_position_pct

    def calculate(
        self,
        estimated_prob: float,
        market_price: float,
        bankroll: float,
        direction: str = "yes",
    ) -> PositionSize:
        """
        Calculate optimal position size using fractional Kelly.

        Args:
            estimated_prob: Our estimated probability (0-1)
            market_price: Current market price (0-1)
            bankroll: Total available capital
            direction: "yes" or "no"
        """
        if direction == "no":
            # Flip for NO bets
            estimated_prob = 1 - estimated_prob
            market_price = 1 - market_price

        # Odds in decimal format: payout per dollar risked
        if market_price <= 0 or market_price >= 1:
            return PositionSize(0, 0, 0, 0, 0)

        # b = net odds (profit per $1 bet if win)
        b = (1 - market_price) / market_price  # e.g., price=0.4 -> b=1.5

        # Kelly formula: f* = (bp - q) / b
        # where p = prob of winning, q = 1-p
        p = estimated_prob
        q = 1 - p

        kelly_full = (b * p - q) / b if b > 0 else 0
        kelly_full = max(0, kelly_full)  # never negative (don't bet)

        # Apply fractional Kelly
        kelly_frac = kelly_full * self.fraction

        # Cap at max position size
        kelly_frac = min(kelly_frac, self.max_position_pct)

        bet_size = bankroll * kelly_frac

        # Expected value
        ev = (p * b - q) * bet_size / (1 + b) if b > 0 else 0

        # Risk/reward
        risk_reward = b if market_price > 0 else 0

        return PositionSize(
            kelly_full=round(kelly_full, 4),
            kelly_fraction=round(kelly_frac, 4),
            bet_size_usd=round(bet_size, 2),
            expected_value=round(ev, 2),
            risk_reward_ratio=round(risk_reward, 2),
        )
