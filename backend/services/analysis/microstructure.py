"""Order Book Microstructure - HFT-light signals for 5m/15m crypto markets.

Based on the user's HFT microstructure document. Implements:
- Queue Imbalance (top-of-book pressure)
- Order Flow Imbalance (OFI)
- Microprice (better than mid-price)
- Spread analysis
- Depth measurement
- Eligibility filters

These are the PRIMARY signals for short-term binary markets, not RSI/MACD.
The edge in 5m/15m markets comes from reading the book state, not chart patterns.
"""

import json
import httpx
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class OrderBookSnapshot:
    """Single moment of an order book."""
    timestamp: datetime
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float
    bid_depth: float  # total volume at best bid
    ask_depth: float
    spread: float
    spread_pct: float  # spread as % of mid
    mid_price: float


@dataclass
class MicrostructureSignals:
    """All microstructure metrics for one market at one moment."""
    queue_imbalance: float  # -1 to 1, positive = buy pressure
    microprice: float  # better than mid for short-term direction
    spread: float
    spread_pct: float
    depth_top: float  # total top-of-book volume
    direction_signal: str  # "bullish", "bearish", "neutral"
    confidence: float  # 0-1, how strong is the signal
    eligible: bool  # passed eligibility filters
    eligibility_reason: str


def queue_imbalance(bid_size: float, ask_size: float) -> float:
    """
    Queue imbalance: (bid - ask) / (bid + ask)
    Returns -1 to 1. Positive = more buy pressure (likely up).

    Reference: Gould & Bonart (arXiv:1512.03492)
    """
    total = bid_size + ask_size
    if total == 0:
        return 0
    return (bid_size - ask_size) / total


def microprice(best_bid: float, best_ask: float, bid_size: float, ask_size: float) -> float:
    """
    Microprice: weighted by inverse queue size.
    Better than mid-price for short-term direction.

    microprice = (ask * bid_size + bid * ask_size) / (bid_size + ask_size)

    The intuition: if there's much more size on the bid, the next move is likely up,
    so the "true" price is closer to the ask.
    """
    total = bid_size + ask_size
    if total == 0:
        return (best_bid + best_ask) / 2
    return (best_ask * bid_size + best_bid * ask_size) / total


def order_flow_imbalance(prev_snapshot: OrderBookSnapshot, curr_snapshot: OrderBookSnapshot) -> float:
    """
    Order Flow Imbalance (OFI) - Cont et al.
    Captures net pressure from order changes between two snapshots.

    Positive OFI = buying pressure increased
    Negative OFI = selling pressure increased
    """
    # Bid side OFI
    if curr_snapshot.best_bid > prev_snapshot.best_bid:
        bid_ofi = curr_snapshot.bid_size  # new bid placed at higher price
    elif curr_snapshot.best_bid < prev_snapshot.best_bid:
        bid_ofi = -prev_snapshot.bid_size  # bid pulled
    else:
        bid_ofi = curr_snapshot.bid_size - prev_snapshot.bid_size

    # Ask side OFI (inverted: more ask = selling pressure)
    if curr_snapshot.best_ask < prev_snapshot.best_ask:
        ask_ofi = curr_snapshot.ask_size
    elif curr_snapshot.best_ask > prev_snapshot.best_ask:
        ask_ofi = -prev_snapshot.ask_size
    else:
        ask_ofi = curr_snapshot.ask_size - prev_snapshot.ask_size

    return bid_ofi - ask_ofi


class PolymarketBookReader:
    """Fetches and parses Polymarket order book snapshots."""

    BASE_URL = "https://clob.polymarket.com"

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=10.0)

    async def get_book(self, token_id: str) -> Optional[OrderBookSnapshot]:
        """Fetch current order book for a token."""
        try:
            resp = await self._http.get(f"{self.BASE_URL}/book", params={"token_id": token_id})
            if resp.status_code != 200:
                return None
            data = resp.json()
            return self._parse_book(data)
        except Exception as e:
            print(f"[BookReader] Error fetching book: {e}")
            return None

    async def get_midpoint(self, token_id: str) -> Optional[float]:
        """Quick midpoint fetch."""
        try:
            resp = await self._http.get(f"{self.BASE_URL}/midpoint", params={"token_id": token_id})
            if resp.status_code == 200:
                return float(resp.json().get("mid", 0))
        except:
            pass
        return None

    @staticmethod
    def _parse_book(data: dict) -> Optional[OrderBookSnapshot]:
        """Parse Polymarket book response into snapshot.

        IMPORTANT: Polymarket book ordering is INVERTED from traditional CLOBs:
        - bids are sorted LOW to HIGH (best bid = last element)
        - asks are sorted HIGH to LOW (best ask = last element)
        """
        try:
            bids = data.get("bids", [])
            asks = data.get("asks", [])

            if not bids or not asks:
                return None

            # Polymarket: best bid is the LAST element (highest price)
            # Polymarket: best ask is the LAST element (lowest price)
            best_bid = float(bids[-1]["price"])
            best_ask = float(asks[-1]["price"])
            bid_size = float(bids[-1]["size"])
            ask_size = float(asks[-1]["size"])

            # Top 3 levels for depth = last 3 of each
            top_bids = bids[-3:] if len(bids) >= 3 else bids
            top_asks = asks[-3:] if len(asks) >= 3 else asks
            bid_depth = sum(float(b["size"]) for b in top_bids)
            ask_depth = sum(float(a["size"]) for a in top_asks)

            mid = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
            spread_pct = spread / mid if mid > 0 else 0

            return OrderBookSnapshot(
                timestamp=datetime.now(timezone.utc),
                best_bid=best_bid,
                best_ask=best_ask,
                bid_size=bid_size,
                ask_size=ask_size,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
                spread=spread,
                spread_pct=spread_pct,
                mid_price=mid,
            )
        except Exception as e:
            print(f"[BookReader] Parse error: {e}")
            return None

    async def close(self):
        await self._http.aclose()


def analyze_book(snapshot: OrderBookSnapshot) -> MicrostructureSignals:
    """
    Analyze a single book snapshot and produce trading signals.

    Eligibility checks (from the document):
    - Spread must be tight enough
    - Top-of-book depth must be enough
    - Otherwise: NOT eligible (no trade)
    """
    if snapshot is None:
        return MicrostructureSignals(
            queue_imbalance=0, microprice=0.5, spread=1, spread_pct=1,
            depth_top=0, direction_signal="neutral", confidence=0,
            eligible=False, eligibility_reason="No book data",
        )

    # Calculate metrics
    qi = queue_imbalance(snapshot.bid_size, snapshot.ask_size)
    mp = microprice(snapshot.best_bid, snapshot.best_ask, snapshot.bid_size, snapshot.ask_size)
    depth = snapshot.bid_depth + snapshot.ask_depth

    # Eligibility filters (from microstructure doc)
    # Spread tolerance scales with price - tighter for normal prices
    eligible = True
    reason = "OK"

    # Use absolute spread (in cents) - more meaningful for binary markets
    abs_spread = snapshot.spread
    if abs_spread > 0.03:  # spread > 3 cents = avoid (too costly)
        eligible = False
        reason = f"Spread too wide: ${abs_spread:.4f}"
    elif depth < 50:  # less than $50 total top-of-book
        eligible = False
        reason = f"Depth too thin: ${depth:.0f}"
    elif snapshot.best_bid <= 0.02 or snapshot.best_ask >= 0.98:
        eligible = False
        reason = f"Extreme prices: bid={snapshot.best_bid:.3f} ask={snapshot.best_ask:.3f}"

    # Determine direction from microstructure
    direction = "neutral"
    confidence = 0.0

    # Strong signal: queue imbalance > 0.4 AND microprice diverges from mid
    mid = snapshot.mid_price
    micro_divergence = (mp - mid) / mid if mid > 0 else 0

    if qi > 0.4 and micro_divergence > 0.005:
        direction = "bullish"
        confidence = min(0.9, abs(qi) * 0.7 + abs(micro_divergence) * 30)
    elif qi < -0.4 and micro_divergence < -0.005:
        direction = "bearish"
        confidence = min(0.9, abs(qi) * 0.7 + abs(micro_divergence) * 30)
    elif abs(qi) > 0.6:  # very strong imbalance even without microprice divergence
        direction = "bullish" if qi > 0 else "bearish"
        confidence = abs(qi) * 0.6
    else:
        direction = "neutral"
        confidence = 0.0

    return MicrostructureSignals(
        queue_imbalance=qi,
        microprice=mp,
        spread=snapshot.spread,
        spread_pct=snapshot.spread_pct,
        depth_top=depth,
        direction_signal=direction,
        confidence=confidence,
        eligible=eligible,
        eligibility_reason=reason,
    )


def is_short_term_crypto_market(market: dict) -> bool:
    """
    Detect if market is a 5m/15m crypto market suitable for HFT-light strategy.

    Polymarket 5m/15m crypto markets typically have:
    - "5 minutes" or "15 minutes" or "Up or Down" in question
    - Crypto symbol (BTC, ETH, etc.)
    - Very short end_date (within an hour)
    """
    question = market.get("question", "").lower()

    # Check for short-term keywords
    short_term_keywords = [
        "5 minute", "15 minute", "next 5 min", "next 15 min",
        "up or down", "in 5 min", "in 15 min",
    ]
    is_short_term = any(kw in question for kw in short_term_keywords)

    # Check for crypto
    crypto_keywords = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "ripple"]
    is_crypto = any(kw in question for kw in crypto_keywords)

    return is_short_term and is_crypto


def confidence_after_costs(
    raw_confidence: float,
    edge: float,
    fee_pct: float = 0.018,  # Polymarket crypto taker fee
) -> tuple[float, bool]:
    """
    Adjust confidence by execution costs.
    Returns (net_confidence, is_profitable).

    The doc says: "decisão correta é: há edge líquido suficiente neste preço e nesta fila?"
    """
    # Subtract fees from edge
    net_edge = abs(edge) - fee_pct
    if net_edge <= 0:
        return 0, False

    # Confidence is reduced when edge is barely above costs
    confidence_multiplier = min(1.0, net_edge / 0.05)  # full confidence at 5% net edge
    net_conf = raw_confidence * confidence_multiplier

    # Profitable if net edge > 1% AND confidence > 70%
    profitable = net_edge >= 0.01 and net_conf >= 0.7

    return net_conf, profitable
