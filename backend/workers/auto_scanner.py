"""Automated scanner - runs periodically to find and execute opportunities."""

import asyncio
from datetime import datetime, timezone
from services.polymarket.client import PolymarketClient
from services.news.pipeline import NewsPipeline
from services.analysis.scorer import OpportunityScorer
from services.analysis.deep_analyst import DeepAnalyst
from services.analysis.feedback import FeedbackEngine
from services.risk.kelly import KellySizer
from services.storage import StorageService
from services.telegram_bot import TelegramAlert
from core.config import get_settings


async def run_scan(
    min_edge: float = 0.10,
    min_score: float = 0.30,
    max_trades: int = 3,
    use_llm: bool = True,
    bankroll: float | None = None,
    bet_size: float | None = None,  # fixed bet size (like the other guy uses $25)
):
    """Run a full scan cycle: collect data, analyze, and optionally trade."""
    settings = get_settings()
    poly_client = PolymarketClient()
    pipeline = NewsPipeline()
    scorer = OpportunityScorer()
    sizer = KellySizer()
    telegram = TelegramAlert()

    storage = None
    try:
        storage = StorageService()
        storage._check()
    except:
        storage = None

    try:
        print(f"\n{'='*60}")
        print(f"[Scanner] Starting scan at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"{'='*60}")

        # 1. Fetch markets
        markets = await poly_client.get_active_markets(limit=100)
        print(f"[Scanner] Markets scanned: {len(markets)}")

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
        print(f"[Scanner] Headlines found: {len(all_news)}")

        if storage:
            storage.save_news(all_news)

        # 4. Get past trade lessons for feedback loop
        past_lessons = ""
        if storage and use_llm:
            try:
                feedback = FeedbackEngine()
                past_trades = storage.get_trades(limit=50)
                resolved = [t for t in past_trades if t.get("pnl") is not None]
                if resolved:
                    past_lessons = await feedback.get_lessons_summary(resolved)
                    print(f"[Scanner] Loaded {len(resolved)} past trade lessons")
            except:
                pass

        # 5. Quick score all markets (Pass 1 - no LLM, fast filter)
        candidates = []
        for market in markets:
            question = market.get("question", "")
            if not question:
                continue
            news = await pipeline.collect_for_market(question, max_results=3)
            score = scorer.score_opportunity(market, news)
            # Pre-filter: only analyze markets with some potential edge
            if abs(score.edge) >= 0.02:
                candidates.append((market, news, score))

        candidates.sort(key=lambda x: abs(x[2].edge), reverse=True)
        print(f"[Scanner] Candidates after pre-filter: {len(candidates)}")

        # 6. Deep analysis on top candidates
        results = []
        trades_executed = 0

        for market, news, initial_score in candidates[:max_trades * 3]:
            if trades_executed >= max_trades:
                break

            question = market.get("question", "")
            current_price = initial_score.current_price

            # Deep multi-pass analysis with Claude
            llm_analysis = None
            if use_llm and settings.anthropic_api_key:
                try:
                    analyst = DeepAnalyst()
                    llm_analysis = await analyst.full_analysis(
                        market, news, past_lessons=past_lessons
                    )
                    await analyst.close()

                    # Check final verdict
                    verdict = llm_analysis.get("final_verdict", "SKIP")
                    if verdict == "SKIP":
                        print(f"[Scanner] SKIP: '{question[:50]}' - Claude says skip")
                        continue
                except Exception as e:
                    print(f"[Scanner] LLM error: {e}")

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

            # Apply thresholds
            if abs(score.edge) < min_edge:
                continue
            if score.score < min_score:
                continue

            # Calculate sizing
            if bet_size:
                size_usd = min(bet_size, bankroll * 0.1)  # cap at 10% of bankroll
            else:
                sizing = sizer.calculate(
                    estimated_prob=score.estimated_probability,
                    market_price=score.current_price,
                    bankroll=bankroll,
                    direction=score.direction,
                )
                size_usd = sizing.bet_size_usd

            if size_usd < 1.0:
                continue

            # Build reasoning
            reasoning = ""
            if llm_analysis:
                reasoning = llm_analysis.get("reasoning", "")
                factors = llm_analysis.get("key_factors", [])
                if factors:
                    reasoning += " | Factors: " + ", ".join(factors[:3])
                devil = llm_analysis.get("devils_advocate", "")
                if devil:
                    reasoning += f" | Risk: {devil[:100]}"
                verdict = llm_analysis.get("final_verdict", "")
                if verdict:
                    reasoning += f" | Verdict: {verdict}"
            else:
                reasoning = f"Sentiment-based: news sentiment {score.news_sentiment:+.2f} across {score.news_count} articles suggests edge of {score.edge*100:.1f}%"

            # Save analysis
            analysis_id = None
            if storage:
                saved = storage.save_analysis({
                    "market_id": score.market_id,
                    "reasoning": reasoning,
                    "confidence": score.confidence,
                    "direction": score.direction,
                    "probability": score.estimated_probability,
                    "market_price": score.current_price,
                    "edge": score.edge,
                    "recommended_action": f"buy_{score.direction}",
                    "recommended_size": size_usd,
                    "kelly_fraction": size_usd / bankroll if bankroll > 0 else 0,
                })
                analysis_id = saved.get("id")

            # Save trade
            price = score.current_price if score.direction == "yes" else (1 - score.current_price)
            trade_data = {
                "market_id": score.market_id,
                "question": question,
                "side": "buy",
                "direction": score.direction,
                "price": price,
                "size": size_usd / price if price > 0 else 0,
                "cost": size_usd,
                "status": "simulated",
                "edge": score.edge,
                "end_date": market.get("endDate"),
                "reasoning": reasoning,
                "analysis_id": analysis_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if storage:
                storage.save_trade(trade_data)
                portfolio = storage.get_portfolio()
                storage.update_portfolio({
                    "invested": portfolio["invested"] + size_usd,
                    "available": portfolio["available"] - size_usd,
                })

            await telegram.notify_trade(trade_data, llm_analysis)

            trades_executed += 1
            claude_prob = llm_analysis["probability"] if llm_analysis else "N/A"
            print(f"[Scanner] TRADE #{trades_executed}: {score.direction.upper()} '{question[:50]}' | Claude: {claude_prob} | Edge: {score.edge*100:.1f}% | ${size_usd:.2f}")

            results.append({
                "question": question,
                "direction": score.direction,
                "edge": score.edge,
                "score": score.score,
                "cost": size_usd,
                "claude_probability": llm_analysis["probability"] if llm_analysis else None,
                "market_price": current_price,
                "verdict": llm_analysis.get("final_verdict") if llm_analysis else None,
            })

        print(f"\n[Scanner] Scan complete. {trades_executed}/{len(candidates)} candidates traded.")
        print(f"{'='*60}\n")

        return {
            "scanned": len(markets),
            "opportunities": len(candidates),
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
