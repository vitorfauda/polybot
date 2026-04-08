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
    max_hours: float = Query(36),
    min_hours: float = Query(1),
    bet_size: float = Query(0),
):
    """Auto scan, analyze, and execute trades."""
    from workers.auto_scanner import run_scan
    result = await run_scan(
        min_edge=min_edge,
        min_score=min_score,
        max_trades=max_trades,
        use_llm=use_llm,
        bankroll=bankroll,
        max_hours_to_expiry=max_hours,
        min_hours_to_expiry=min_hours,
        bet_size=bet_size if bet_size > 0 else None,
    )
    storage = _get_storage()
    portfolio = storage.get_stats() if storage else executor.get_portfolio()
    return {**result, "portfolio": portfolio}


@router.post("/scan-profile/{profile_name}")
async def scan_with_profile(profile_name: str):
    """Run a scan using a specific trading profile (hunter, sniper, scout)."""
    from workers.auto_scanner import run_profile_scan
    from services.profiles import get_profile
    profile = get_profile(profile_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")
    result = await run_profile_scan(profile)
    return result


@router.post("/scan-all-profiles")
async def scan_all_profiles():
    """Run scans for all 3 profiles in sequence."""
    from workers.auto_scanner import run_all_profiles
    return await run_all_profiles()


@router.get("/profiles")
async def list_profiles():
    """List all available trading profiles with their settings and current portfolios."""
    from services.profiles import all_profiles
    storage = _get_storage()
    profiles = []
    for p in all_profiles():
        portfolio = None
        trades = []
        if storage:
            try:
                portfolio = storage.get_portfolio(profile=p.name)
                trades = storage.get_trades(limit=20, profile=p.name)
            except:
                pass

        # Calculate stats
        wins = sum(1 for t in trades if t.get("status") == "won")
        losses = sum(1 for t in trades if t.get("status") == "lost")
        open_count = sum(1 for t in trades if t.get("status") == "simulated")
        win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0

        profiles.append({
            "name": p.name,
            "display_name": p.display_name,
            "description": p.description,
            "settings": {
                "min_edge": p.min_edge,
                "min_confidence": p.min_claude_confidence,
                "bet_size": p.bet_size_usd,
                "max_hours": p.max_hours_to_expiry,
                "required_verdict": p.required_verdict,
            },
            "portfolio": portfolio,
            "stats": {
                "total_trades": len(trades),
                "open": open_count,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
            },
            "recent_trades": trades[:5],
        })
    return {"profiles": profiles}


@router.post("/resolve-all")
async def resolve_all_trades():
    """Manually trigger resolution of all expired open trades."""
    from workers.auto_resolver import resolve_open_trades
    return await resolve_open_trades()


@router.post("/scan-crypto")
async def scan_crypto_markets(
    max_markets: int = Query(20),
    min_edge: float = Query(0.05),
    bet_size: float = Query(10),
    execute: bool = Query(False, description="If true, execute trades. If false, just analyze."),
):
    """
    Specialized crypto market scanner.
    Uses real-time price data, technical indicators, and Claude AI analysis.
    """
    from services.polymarket.client import PolymarketClient
    from services.news.pipeline import NewsPipeline
    from services.analysis.crypto_strategy import CryptoIntelligence
    from datetime import datetime, timezone

    poly_client = PolymarketClient()
    pipeline = NewsPipeline()
    intel = CryptoIntelligence()
    storage = _get_storage()
    telegram = TelegramAlert()

    try:
        # Fetch markets
        all_markets = await poly_client.get_active_markets(limit=200)

        # Filter to crypto only
        crypto_markets = [m for m in all_markets if intel.is_crypto_market(m)]
        print(f"[CryptoScan] Found {len(crypto_markets)} crypto markets out of {len(all_markets)}")

        results = []
        executed = 0

        for market in crypto_markets[:max_markets]:
            question = market.get("question", "")

            # Collect crypto-specific news
            news = await pipeline.collect_for_market(question, max_results=5)

            # Run full crypto analysis with real data
            try:
                analysis = await intel.analyze_crypto_market(market, news)
            except Exception as e:
                print(f"[CryptoScan] Error analyzing '{question[:40]}': {e}")
                continue

            if "error" in analysis:
                continue

            verdict = analysis.get("claude_verdict", {})
            recommendation = verdict.get("trade_recommendation", "SKIP")

            # Calculate edge
            import json as _json
            prices = market.get("outcomePrices", "[0.5,0.5]")
            if isinstance(prices, str):
                try:
                    prices = _json.loads(prices)
                except:
                    prices = [0.5, 0.5]
            market_yes = float(prices[0]) if prices else 0.5

            claude_prob = verdict.get("probability", market_yes)
            direction = verdict.get("direction", "yes")
            edge = (claude_prob - market_yes) if direction == "yes" else ((1 - claude_prob) - (1 - market_yes))

            result_entry = {
                "question": question,
                "coin": analysis["coin"],
                "current_price": analysis["analysis"]["current_price"],
                "target_price": analysis["analysis"]["target_price"],
                "distance_pct": analysis["analysis"]["distance_to_target_pct"],
                "rsi": analysis["analysis"]["rsi"],
                "technical": analysis["analysis"]["technical_signal"],
                "market_price": market_yes,
                "claude_probability": claude_prob,
                "edge": edge,
                "direction": direction,
                "recommendation": recommendation,
                "reasoning": verdict.get("reasoning", ""),
                "key_signal": verdict.get("key_signal", ""),
                "risk": verdict.get("risk", ""),
            }

            results.append(result_entry)

            # Execute trade if conditions met
            if execute and recommendation in ("STRONG_BUY", "BUY") and abs(edge) >= min_edge:
                if executed >= 3:
                    continue
                price = market_yes if direction == "yes" else (1 - market_yes)
                trade_data = {
                    "market_id": market.get("conditionId", market.get("id", "")),
                    "question": question,
                    "side": "buy",
                    "direction": direction,
                    "price": price,
                    "size": bet_size / price if price > 0 else 0,
                    "cost": bet_size,
                    "status": "simulated",
                    "edge": edge,
                    "end_date": market.get("endDate"),
                    "reasoning": f"[CRYPTO] {verdict.get('reasoning', '')[:300]} | Signal: {verdict.get('key_signal', '')[:100]} | Risk: {verdict.get('risk', '')[:100]}",
                    "profile": "crypto_hunter",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                if storage:
                    storage.save_trade(trade_data)
                    portfolio = storage.get_portfolio(profile="crypto_hunter")
                    if portfolio:
                        storage.update_portfolio({
                            "invested": portfolio["invested"] + bet_size,
                            "available": portfolio["available"] - bet_size,
                        }, profile="crypto_hunter")

                await telegram.notify_trade(trade_data, verdict)
                executed += 1
                print(f"[CryptoScan] EXECUTED: {direction.upper()} '{question[:50]}' edge={edge*100:.1f}%")

        return {
            "scanned": len(all_markets),
            "crypto_markets_found": len(crypto_markets),
            "analyzed": len(results),
            "executed": executed,
            "results": results,
        }
    finally:
        await poly_client.close()
        await pipeline.close()
        await intel.close()
