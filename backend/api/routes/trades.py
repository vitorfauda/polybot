"""Trade routes - execute simulated trades and manage portfolio."""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from services.polymarket.client import PolymarketClient
from services.polymarket.executor import TradeExecutor, ExecutionMode
from services.news.pipeline import NewsPipeline
from services.analysis.scorer import OpportunityScorer
from services.analysis.llm_analyst import LLMAnalyst
from services.risk.kelly import KellySizer
from services.storage import StorageService
from services.telegram_bot import TelegramAlert

router = APIRouter()

# In-memory executor (fallback)
executor = TradeExecutor(mode=ExecutionMode.SIMULATION)

# Supabase storage (optional - degrades gracefully)
def _get_storage() -> StorageService | None:
    try:
        s = StorageService()
        s._check()
        return s
    except:
        return None


class TradeRequest(BaseModel):
    market_id: str
    direction: str = "yes"
    amount_usd: float = 0
    use_llm: bool = True


class ResolveRequest(BaseModel):
    trade_id: int
    outcome: str  # "yes" or "no"


@router.get("/portfolio")
async def get_portfolio():
    """Get current portfolio state."""
    storage = _get_storage()
    if storage:
        return storage.get_stats()
    return executor.get_portfolio()


@router.get("/positions")
async def get_positions():
    """Get all positions (open and closed)."""
    storage = _get_storage()
    if storage:
        open_trades = storage.get_open_trades()
        closed = storage.get_trades(limit=50)
        closed = [t for t in closed if t.get("status") in ("won", "lost")]
        return {"positions": open_trades + closed, "count": len(open_trades) + len(closed)}
    positions = executor.get_positions()
    return {"positions": positions, "count": len(positions)}


@router.get("/history")
async def get_trade_history():
    """Get trade history."""
    storage = _get_storage()
    if storage:
        trades = storage.get_trades(limit=100)
        return {"trades": trades, "count": len(trades)}
    trades = executor.get_trades()
    return {"trades": trades, "count": len(trades)}


@router.post("/execute")
async def execute_trade(req: TradeRequest):
    """Execute a simulated trade on a market."""
    poly_client = PolymarketClient()
    pipeline = NewsPipeline()
    scorer = OpportunityScorer()
    sizer = KellySizer()
    storage = _get_storage()
    telegram = TelegramAlert()

    try:
        markets = await poly_client.get_active_markets(limit=100)
        market = None
        for m in markets:
            if m.get("conditionId") == req.market_id or m.get("id") == req.market_id:
                market = m
                break

        if not market:
            raise HTTPException(status_code=404, detail=f"Market {req.market_id} not found")

        question = market.get("question", "")
        news = await pipeline.collect_for_market(question, max_results=5)

        llm_analysis = None
        if req.use_llm:
            try:
                analyst = LLMAnalyst()
                llm_analysis = await analyst.analyze_market(market, news)
            except Exception as e:
                print(f"[Trade] LLM analysis failed: {e}")

        score = scorer.score_opportunity(
            market, news,
            llm_probability=llm_analysis["probability"] if llm_analysis else None,
            llm_confidence=llm_analysis["confidence"] if llm_analysis else None,
            llm_reasoning=llm_analysis.get("reasoning") if llm_analysis else None,
        )

        # Get bankroll
        if storage:
            portfolio = storage.get_portfolio()
            bankroll = portfolio.get("available", portfolio.get("total_balance", 1000))
        else:
            portfolio = executor.get_portfolio()
            bankroll = portfolio["balance"]

        if req.amount_usd > 0:
            size_usd = min(req.amount_usd, bankroll)
        else:
            sizing = sizer.calculate(
                estimated_prob=score.estimated_probability,
                market_price=score.current_price,
                bankroll=bankroll,
                direction=req.direction,
            )
            size_usd = sizing.bet_size_usd

        if size_usd < 0.01:
            return {"status": "rejected", "reason": "No edge or insufficient bankroll"}

        price = score.current_price if req.direction == "yes" else (1 - score.current_price)
        trade_data = {
            "market_id": score.market_id,
            "question": question,
            "side": "buy",
            "direction": req.direction,
            "price": price,
            "size": size_usd / price if price > 0 else 0,
            "cost": size_usd,
            "status": "simulated",
            "edge": score.edge,
        }

        # Persist
        if storage:
            saved = storage.save_trade(trade_data)
            storage.update_portfolio({
                "invested": portfolio["invested"] + size_usd,
                "available": portfolio["available"] - size_usd,
            })
            await telegram.notify_trade(trade_data, llm_analysis)
            return {"trade": saved, "analysis": llm_analysis, "portfolio": storage.get_stats()}
        else:
            result = await executor.execute_trade(market, req.direction, size_usd, price, edge=score.edge)
            return {"trade": result.to_dict(), "analysis": llm_analysis, "portfolio": executor.get_portfolio()}

    finally:
        await poly_client.close()
        await pipeline.close()


@router.post("/resolve")
async def resolve_position(req: ResolveRequest):
    """Resolve a simulated position."""
    storage = _get_storage()
    telegram = TelegramAlert()

    if storage:
        # Get trade
        trades = storage.get_trades(limit=200)
        trade = None
        for t in trades:
            if t["id"] == req.trade_id:
                trade = t
                break
        if not trade:
            raise HTTPException(status_code=404, detail=f"Trade {req.trade_id} not found")

        won = trade["direction"] == req.outcome
        if won:
            payout = trade["size"] * 1.0
            pnl = payout - trade["cost"]
        else:
            payout = 0
            pnl = -trade["cost"]

        storage.resolve_trade(req.trade_id, req.outcome, round(pnl, 2))

        # Update portfolio
        portfolio = storage.get_portfolio()
        storage.update_portfolio({
            "invested": max(0, portfolio["invested"] - trade["cost"]),
            "available": portfolio["available"] + payout,
            "total_pnl": portfolio["total_pnl"] + pnl,
            "total_balance": portfolio["total_balance"] + pnl,
            "win_count": portfolio["win_count"] + (1 if won else 0),
            "loss_count": portfolio["loss_count"] + (0 if won else 1),
        })

        await telegram.notify_resolution({"question": trade.get("market_id"), "pnl": pnl, "outcome": req.outcome})
        return {"resolved": True, "pnl": round(pnl, 2), "portfolio": storage.get_stats()}
    else:
        result = executor.resolve_position(str(req.trade_id), req.outcome)
        if result is None:
            raise HTTPException(status_code=404, detail="Position not found")
        return {"resolved": result, "portfolio": executor.get_portfolio()}


@router.post("/auto-scan")
async def auto_scan_and_trade(
    bankroll: float = Query(1000),
    min_edge: float = Query(0.05),
    min_score: float = Query(0.4),
    max_trades: int = Query(3),
    use_llm: bool = Query(True),
):
    """Auto scan, analyze, and execute trades."""
    from workers.auto_scanner import run_scan
    result = await run_scan(
        min_edge=min_edge,
        min_score=min_score,
        max_trades=max_trades,
        use_llm=use_llm,
        bankroll=bankroll,
    )
    storage = _get_storage()
    portfolio = storage.get_stats() if storage else executor.get_portfolio()
    return {**result, "portfolio": portfolio}
