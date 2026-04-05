"""Automated scanner - runs periodically to find and execute opportunities."""

import asyncio
from datetime import datetime, timezone
from services.polymarket.client import PolymarketClient
from services.news.pipeline import NewsPipeline
from services.analysis.scorer import OpportunityScorer
from services.analysis.llm_analyst import LLMAnalyst
from services.risk.kelly import KellySizer
from services.storage import StorageService
from services.telegram_bot import TelegramAlert
from core.config import get_settings


async def run_scan(
    min_edge: float = 0.05,
    min_score: float = 0.35,
    max_trades: int = 3,
    use_llm: bool = True,
    bankroll: float | None = None,
):
    """Run a full scan cycle: collect data, analyze, and optionally trade."""
    settings = get_settings()
    poly_client = PolymarketClient()
    pipeline = NewsPipeline()
    scorer = OpportunityScorer()
    sizer = KellySizer()
    telegram = TelegramAlert()

    # Storage (optional - works without it)
    storage = None
    try:
        storage = StorageService()
        storage._check()
    except:
        storage = None

    try:
        print(f"[Scanner] Starting scan at {datetime.now(timezone.utc).isoformat()}")

        # 1. Fetch markets
        markets = await poly_client.get_active_markets(limit=50)
        print(f"[Scanner] Fetched {len(markets)} markets")

        # Save markets to DB
        if storage:
            storage.save_markets(markets)

        # 2. Get portfolio balance
        if bankroll is None:
            if storage:
                portfolio = storage.get_portfolio()
                bankroll = portfolio.get("available", portfolio.get("total_balance", 1000))
            else:
                bankroll = 1000

        # 3. Collect news
        all_news = await pipeline.collect_all()
        print(f"[Scanner] Collected {len(all_news)} news articles")

        if storage:
            storage.save_news(all_news)

        # 4. Score markets
        scored = []
        for market in markets:
            question = market.get("question", "")
            if not question:
                continue
            news = await pipeline.collect_for_market(question, max_results=3)
            score = scorer.score_opportunity(market, news)
            if abs(score.edge) >= min_edge:
                scored.append((market, news, score))

        scored.sort(key=lambda x: x[2].score, reverse=True)
        print(f"[Scanner] Found {len(scored)} opportunities above {min_edge*100}% edge")

        # 5. Analyze top opportunities with LLM
        results = []
        trades_executed = 0

        for market, news, initial_score in scored[:max_trades * 2]:
            if trades_executed >= max_trades:
                break

            llm_analysis = None
            if use_llm and settings.anthropic_api_key:
                try:
                    analyst = LLMAnalyst()
                    llm_analysis = await analyst.analyze_market(market, news)
                except Exception as e:
                    print(f"[Scanner] LLM error: {e}")

            # Re-score with LLM
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
                continue

            # Calculate sizing
            sizing = sizer.calculate(
                estimated_prob=score.estimated_probability,
                market_price=score.current_price,
                bankroll=bankroll,
                direction=score.direction,
            )

            if sizing.bet_size_usd < 1.0:
                continue

            # Save analysis
            analysis_id = None
            if storage:
                saved = storage.save_analysis({
                    "market_id": score.market_id,
                    "reasoning": llm_analysis.get("reasoning", "") if llm_analysis else "",
                    "confidence": score.confidence,
                    "direction": score.direction,
                    "probability": score.estimated_probability,
                    "market_price": score.current_price,
                    "edge": score.edge,
                    "recommended_action": f"buy_{score.direction}",
                    "recommended_size": sizing.bet_size_usd,
                    "kelly_fraction": sizing.kelly_fraction,
                })
                analysis_id = saved.get("id")

            # Save trade
            trade_data = {
                "market_id": score.market_id,
                "question": market.get("question", ""),
                "side": "buy",
                "direction": score.direction,
                "price": score.current_price if score.direction == "yes" else (1 - score.current_price),
                "size": sizing.bet_size_usd / score.current_price if score.current_price > 0 else 0,
                "cost": sizing.bet_size_usd,
                "status": "simulated",
                "edge": score.edge,
                "analysis_id": analysis_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if storage:
                saved_trade = storage.save_trade(trade_data)
                # Update portfolio
                portfolio = storage.get_portfolio()
                storage.update_portfolio({
                    "invested": portfolio["invested"] + sizing.bet_size_usd,
                    "available": portfolio["available"] - sizing.bet_size_usd,
                })

            # Send Telegram alert
            await telegram.notify_trade(trade_data, llm_analysis)

            trades_executed += 1
            results.append({
                "question": market.get("question", ""),
                "direction": score.direction,
                "edge": score.edge,
                "score": score.score,
                "cost": sizing.bet_size_usd,
            })
            print(f"[Scanner] Trade #{trades_executed}: {score.direction.upper()} on '{market.get('question', '')[:50]}' | Edge: {score.edge*100:.1f}% | ${sizing.bet_size_usd:.2f}")

        print(f"[Scanner] Scan complete. {trades_executed} trades executed.")
        return {
            "scanned": len(markets),
            "opportunities": len(scored),
            "trades": trades_executed,
            "results": results,
        }

    finally:
        await poly_client.close()
        await pipeline.close()


async def run_loop(interval_minutes: int = 30, **kwargs):
    """Run scanner in a loop."""
    print(f"[Scanner] Starting auto-scan loop (every {interval_minutes}min)")
    while True:
        try:
            await run_scan(**kwargs)
        except Exception as e:
            print(f"[Scanner] Error: {e}")
        await asyncio.sleep(interval_minutes * 60)


if __name__ == "__main__":
    asyncio.run(run_scan())
