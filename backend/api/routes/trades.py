"""Trade routes - execute simulated trades and manage portfolio."""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from services.polymarket.client import PolymarketClient
from services.polymarket.executor import TradeExecutor, ExecutionMode
from services.news.pipeline import NewsPipeline
from services.analysis.scorer import OpportunityScorer
from services.analysis.llm_analyst import LLMAnalyst
from services.risk.kelly import KellySizer

router = APIRouter()

# Global executor instance (in-memory for now, will move to DB later)
executor = TradeExecutor(mode=ExecutionMode.SIMULATION)


class TradeRequest(BaseModel):
    market_id: str
    direction: str = "yes"  # "yes" or "no"
    amount_usd: float = 0  # 0 = use Kelly sizing
    use_llm: bool = True


class ResolveRequest(BaseModel):
    trade_id: str
    outcome: str  # "yes" or "no"


@router.get("/portfolio")
async def get_portfolio():
    """Get current portfolio state."""
    return executor.get_portfolio()


@router.get("/positions")
async def get_positions():
    """Get all positions (open and closed)."""
    positions = executor.get_positions()
    return {"positions": positions, "count": len(positions)}


@router.get("/history")
async def get_trade_history():
    """Get trade history."""
    trades = executor.get_trades()
    return {"trades": trades, "count": len(trades)}


@router.post("/execute")
async def execute_trade(req: TradeRequest):
    """Execute a simulated trade on a market."""
    poly_client = PolymarketClient()
    pipeline = NewsPipeline()
    scorer = OpportunityScorer()
    sizer = KellySizer()

    try:
        # Get market data
        markets = await poly_client.get_active_markets(limit=100)
        market = None
        for m in markets:
            if m.get("conditionId") == req.market_id or m.get("id") == req.market_id:
                market = m
                break

        if not market:
            raise HTTPException(status_code=404, detail=f"Market {req.market_id} not found")

        # Get news
        question = market.get("question", "")
        news = await pipeline.collect_for_market(question, max_results=5)

        # Get analysis
        llm_analysis = None
        if req.use_llm:
            try:
                analyst = LLMAnalyst()
                llm_analysis = await analyst.analyze_market(market, news)
            except Exception as e:
                print(f"[Trade] LLM analysis failed: {e}")

        # Score opportunity
        score = scorer.score_opportunity(
            market, news,
            llm_probability=llm_analysis["probability"] if llm_analysis else None,
            llm_confidence=llm_analysis["confidence"] if llm_analysis else None,
            llm_reasoning=llm_analysis.get("reasoning") if llm_analysis else None,
        )

        # Calculate sizing
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
            return {
                "status": "rejected",
                "reason": "Calculated bet size too small (no edge or insufficient bankroll)",
                "score": score.score,
                "edge": score.edge,
                "analysis": llm_analysis,
            }

        # Execute trade
        result = await executor.execute_trade(
            market=market,
            direction=req.direction,
            size_usd=size_usd,
            price=score.current_price if req.direction == "yes" else (1 - score.current_price),
            edge=score.edge,
            kelly_fraction=score.confidence,
        )

        return {
            "trade": result.to_dict(),
            "analysis": llm_analysis,
            "score": {
                "score": score.score,
                "edge": score.edge,
                "confidence": score.confidence,
                "direction": score.direction,
                "estimated_probability": score.estimated_probability,
            },
            "portfolio": executor.get_portfolio(),
        }

    finally:
        await poly_client.close()
        await pipeline.close()


@router.post("/resolve")
async def resolve_position(req: ResolveRequest):
    """Manually resolve a simulated position."""
    result = executor.resolve_position(req.trade_id, req.outcome)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Position {req.trade_id} not found or already closed")
    return {
        "resolved": result,
        "portfolio": executor.get_portfolio(),
    }


@router.post("/auto-scan")
async def auto_scan_and_trade(
    bankroll: float = Query(1000),
    min_edge: float = Query(0.05),
    min_score: float = Query(0.4),
    max_trades: int = Query(3),
    use_llm: bool = Query(True),
):
    """Automatically scan markets, analyze with LLM, and execute best opportunities."""
    poly_client = PolymarketClient()
    pipeline = NewsPipeline()
    scorer = OpportunityScorer()
    sizer = KellySizer()

    try:
        # Fetch markets
        markets = await poly_client.get_active_markets(limit=50)

        # Score all markets with news
        scored = []
        for market in markets:
            question = market.get("question", "")
            if not question:
                continue
            news = await pipeline.collect_for_market(question, max_results=3)
            score = scorer.score_opportunity(market, news)
            if abs(score.edge) >= min_edge:
                scored.append((market, news, score))

        # Sort by score
        scored.sort(key=lambda x: x[2].score, reverse=True)

        # Analyze top opportunities with LLM and potentially trade
        results = []
        trades_executed = 0

        for market, news, initial_score in scored[:max_trades * 2]:
            if trades_executed >= max_trades:
                break

            llm_analysis = None
            if use_llm:
                try:
                    analyst = LLMAnalyst()
                    llm_analysis = await analyst.analyze_market(market, news)
                except:
                    pass

            # Re-score with LLM data
            if llm_analysis:
                score = scorer.score_opportunity(
                    market, news,
                    llm_probability=llm_analysis["probability"],
                    llm_confidence=llm_analysis["confidence"],
                    llm_reasoning=llm_analysis.get("reasoning"),
                )
            else:
                score = initial_score

            if score.score < min_score or abs(score.edge) < min_edge:
                results.append({
                    "market": market.get("question", ""),
                    "action": "skip",
                    "reason": f"Score {score.score:.2f} or edge {score.edge:.3f} below threshold",
                })
                continue

            # Calculate sizing
            portfolio = executor.get_portfolio()
            sizing = sizer.calculate(
                estimated_prob=score.estimated_probability,
                market_price=score.current_price,
                bankroll=portfolio["balance"],
                direction=score.direction,
            )

            if sizing.bet_size_usd < 1.0:
                continue

            # Execute
            trade_result = await executor.execute_trade(
                market=market,
                direction=score.direction,
                size_usd=sizing.bet_size_usd,
                price=score.current_price if score.direction == "yes" else (1 - score.current_price),
                edge=score.edge,
                kelly_fraction=sizing.kelly_fraction,
            )

            trades_executed += 1
            results.append({
                "market": market.get("question", ""),
                "action": "traded",
                "trade": trade_result.to_dict(),
                "analysis": llm_analysis,
                "score": score.score,
                "edge": score.edge,
            })

        return {
            "scanned": len(markets),
            "opportunities_found": len(scored),
            "trades_executed": trades_executed,
            "results": results,
            "portfolio": executor.get_portfolio(),
        }

    finally:
        await poly_client.close()
        await pipeline.close()
