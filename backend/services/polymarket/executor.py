"""Trade executor - handles both simulated and live trades."""

import json
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from enum import Enum


class ExecutionMode(str, Enum):
    SIMULATION = "simulation"
    LIVE = "live"


@dataclass
class TradeResult:
    trade_id: str
    market_id: str
    question: str
    side: str  # "buy" or "sell"
    direction: str  # "yes" or "no"
    price: float
    size: float
    cost: float
    mode: str  # "simulation" or "live"
    status: str  # "filled", "pending", "failed"
    timestamp: str
    analysis_id: int | None = None
    edge: float = 0.0
    kelly_fraction: float = 0.0
    error: str | None = None

    def to_dict(self):
        return asdict(self)


class TradeExecutor:
    """Executes trades in simulation or live mode."""

    def __init__(self, mode: ExecutionMode = ExecutionMode.SIMULATION):
        self.mode = mode
        self._sim_counter = 0
        self._sim_portfolio = {
            "balance": 1000.0,
            "invested": 0.0,
            "positions": [],
            "trades": [],
        }

    async def execute_trade(
        self,
        market: dict,
        direction: str,
        size_usd: float,
        price: float,
        analysis_id: int | None = None,
        edge: float = 0.0,
        kelly_fraction: float = 0.0,
    ) -> TradeResult:
        """Execute a trade (simulated or live)."""
        if self.mode == ExecutionMode.SIMULATION:
            return await self._simulate_trade(
                market, direction, size_usd, price,
                analysis_id, edge, kelly_fraction,
            )
        else:
            return await self._live_trade(
                market, direction, size_usd, price,
                analysis_id, edge, kelly_fraction,
            )

    async def _simulate_trade(
        self,
        market: dict,
        direction: str,
        size_usd: float,
        price: float,
        analysis_id: int | None,
        edge: float,
        kelly_fraction: float,
    ) -> TradeResult:
        """Simulate a trade without real money."""
        self._sim_counter += 1
        trade_id = f"SIM-{self._sim_counter:06d}"

        question = market.get("question", "Unknown")
        market_id = market.get("conditionId", market.get("id", ""))

        # Check if we have enough balance
        if size_usd > self._sim_portfolio["balance"]:
            return TradeResult(
                trade_id=trade_id,
                market_id=market_id,
                question=question,
                side="buy",
                direction=direction,
                price=price,
                size=0,
                cost=0,
                mode="simulation",
                status="failed",
                timestamp=datetime.now(timezone.utc).isoformat(),
                analysis_id=analysis_id,
                edge=edge,
                kelly_fraction=kelly_fraction,
                error=f"Insufficient balance: ${self._sim_portfolio['balance']:.2f} < ${size_usd:.2f}",
            )

        # Calculate shares
        shares = size_usd / price if price > 0 else 0

        # Update simulated portfolio
        self._sim_portfolio["balance"] -= size_usd
        self._sim_portfolio["invested"] += size_usd

        position = {
            "trade_id": trade_id,
            "market_id": market_id,
            "question": question,
            "direction": direction,
            "shares": shares,
            "entry_price": price,
            "cost": size_usd,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "open",
        }
        self._sim_portfolio["positions"].append(position)

        result = TradeResult(
            trade_id=trade_id,
            market_id=market_id,
            question=question,
            side="buy",
            direction=direction,
            price=price,
            size=shares,
            cost=size_usd,
            mode="simulation",
            status="filled",
            timestamp=datetime.now(timezone.utc).isoformat(),
            analysis_id=analysis_id,
            edge=edge,
            kelly_fraction=kelly_fraction,
        )

        self._sim_portfolio["trades"].append(result.to_dict())
        return result

    async def _live_trade(
        self,
        market: dict,
        direction: str,
        size_usd: float,
        price: float,
        analysis_id: int | None,
        edge: float,
        kelly_fraction: float,
    ) -> TradeResult:
        """Execute a real trade on Polymarket. NOT IMPLEMENTED YET."""
        market_id = market.get("conditionId", market.get("id", ""))
        return TradeResult(
            trade_id="LIVE-NOT-IMPLEMENTED",
            market_id=market_id,
            question=market.get("question", ""),
            side="buy",
            direction=direction,
            price=price,
            size=0,
            cost=0,
            mode="live",
            status="failed",
            timestamp=datetime.now(timezone.utc).isoformat(),
            analysis_id=analysis_id,
            edge=edge,
            kelly_fraction=kelly_fraction,
            error="Live trading not yet implemented. Use simulation mode.",
        )

    def get_portfolio(self) -> dict:
        """Get current simulated portfolio state."""
        open_positions = [p for p in self._sim_portfolio["positions"] if p["status"] == "open"]
        closed_positions = [p for p in self._sim_portfolio["positions"] if p["status"] == "closed"]

        total_pnl = sum(p.get("pnl", 0) for p in closed_positions)
        wins = sum(1 for p in closed_positions if p.get("pnl", 0) > 0)
        losses = sum(1 for p in closed_positions if p.get("pnl", 0) <= 0)

        return {
            "mode": self.mode.value,
            "balance": round(self._sim_portfolio["balance"], 2),
            "invested": round(self._sim_portfolio["invested"], 2),
            "total_value": round(self._sim_portfolio["balance"] + self._sim_portfolio["invested"], 2),
            "total_pnl": round(total_pnl, 2),
            "win_count": wins,
            "loss_count": losses,
            "win_rate": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
            "open_positions": len(open_positions),
            "total_trades": len(self._sim_portfolio["trades"]),
        }

    def get_positions(self) -> list[dict]:
        """Get all positions."""
        return self._sim_portfolio["positions"]

    def get_trades(self) -> list[dict]:
        """Get all trade history."""
        return self._sim_portfolio["trades"]

    def resolve_position(self, trade_id: str, outcome: str) -> dict | None:
        """Manually resolve a simulated position. outcome: 'yes' or 'no'."""
        for pos in self._sim_portfolio["positions"]:
            if pos["trade_id"] == trade_id and pos["status"] == "open":
                won = pos["direction"] == outcome
                if won:
                    payout = pos["shares"] * 1.0  # $1 per share
                    pnl = payout - pos["cost"]
                else:
                    payout = 0
                    pnl = -pos["cost"]

                pos["status"] = "closed"
                pos["outcome"] = outcome
                pos["pnl"] = round(pnl, 2)
                pos["payout"] = round(payout, 2)
                pos["resolved_at"] = datetime.now(timezone.utc).isoformat()

                # Update portfolio
                self._sim_portfolio["invested"] -= pos["cost"]
                self._sim_portfolio["balance"] += payout

                return pos
        return None
