"""Automated scanner - runs periodically to find and execute opportunities."""

import asyncio
from datetime import datetime, timezone, timedelta
from dateutil import parser as date_parser
from services.polymarket.client import PolymarketClient
from services.news.pipeline import NewsPipeline
from services.analysis.scorer import OpportunityScorer
from services.analysis.deep_analyst import DeepAnalyst
from services.analysis.feedback import FeedbackEngine
from services.analysis.strategies import StrategyOrchestrator
from services.risk.kelly import KellySizer
from services.storage import StorageService
from services.telegram_bot import TelegramAlert
from services.profiles import TradingProfile, get_profile, all_profiles
from core.config import get_settings


def _hours_until(end_date_str: str | None) -> float | None:
    """Calculate hours until a market expires."""
    if not end_date_str:
        return None
    try:
        end = date_parser.parse(end_date_str)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        delta = end - datetime.now(timezone.utc)
        return delta.total_seconds() / 3600
    except:
        return None


async def run_scan(
    min_edge: float = 0.10,
    min_score: float = 0.30,
    max_trades: int = 3,
    use_llm: bool = True,
    bankroll: float | None = None,
    bet_size: float | None = None,  # fixed bet size (like the other guy uses $25)
    max_hours_to_expiry: float = 36,  # only markets expiring within 36h (today/tomorrow)
    min_hours_to_expiry: float = 1,  # avoid markets expiring in less than 1h
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
        all_markets = await poly_client.get_active_markets(limit=200)
        print(f"[Scanner] Total markets fetched: {len(all_markets)}")

        # Filter by expiry time (same day or next day)
        markets = []
        for m in all_markets:
            hours = _hours_until(m.get("endDate"))
            if hours is None:
                continue
            if min_hours_to_expiry <= hours <= max_hours_to_expiry:
                markets.append(m)
        print(f"[Scanner] Markets expiring in {min_hours_to_expiry}-{max_hours_to_expiry}h: {len(markets)}")

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


async def run_profile_scan(profile: TradingProfile) -> dict:
    """Run a scan using a specific trading profile's filters and rules."""
    settings = get_settings()
    poly_client = PolymarketClient()
    pipeline = NewsPipeline()
    scorer = OpportunityScorer()
    telegram = TelegramAlert()

    storage = None
    try:
        storage = StorageService()
        storage._check()
    except:
        storage = None

    try:
        print(f"\n{'='*60}")
        print(f"[{profile.display_name}] Starting scan at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        print(f"{'='*60}")

        # 1. Fetch markets
        all_markets = await poly_client.get_active_markets(limit=200)

        # 2. Apply profile filters
        markets = []
        for m in all_markets:
            hours = _hours_until(m.get("endDate"))
            if hours is None:
                continue
            if not (profile.min_hours_to_expiry <= hours <= profile.max_hours_to_expiry):
                continue
            volume = float(m.get("volume", 0))
            liquidity = float(m.get("liquidity", 0))
            if volume < profile.min_volume:
                continue
            if liquidity < profile.min_liquidity:
                continue

            # Check extreme prices
            if profile.avoid_extreme_prices:
                import json as _json
                prices = m.get("outcomePrices", "[0.5,0.5]")
                if isinstance(prices, str):
                    try:
                        prices = _json.loads(prices)
                    except:
                        prices = [0.5, 0.5]
                price_yes = float(prices[0]) if prices else 0.5
                if price_yes < profile.extreme_price_threshold or price_yes > (1 - profile.extreme_price_threshold):
                    continue

            markets.append(m)

        print(f"[{profile.display_name}] Markets passing filters: {len(markets)}")

        if storage:
            storage.save_markets(markets)

        # 3. Get bankroll for this profile
        portfolio = storage.get_portfolio(profile=profile.name) if storage else None
        bankroll = portfolio.get("available", 1000) if portfolio else 1000

        # 4. Pre-filter: collect news for all eligible markets, no edge requirement here
        # Strategies will determine if there's an opportunity, not the simple scorer
        candidates = []
        for market in markets[:30]:  # cap to keep scan fast
            question = market.get("question", "")
            if not question:
                continue
            news = await pipeline.collect_for_market(question, max_results=4)
            if len(news) < profile.min_news_count:
                continue
            score = scorer.score_opportunity(market, news)
            candidates.append((market, news, score))

        # Sort by volume (focus on more liquid markets first)
        candidates.sort(key=lambda x: float(x[0].get("volume", 0)), reverse=True)
        print(f"[{profile.display_name}] Candidates with news: {len(candidates)}")

        # 5. Strategy orchestration + deep analysis on top candidates
        results = []
        trades_executed = 0

        # Aggressive profiles (Scout) skip the strategy orchestrator
        # for speed and to actually execute trades
        is_aggressive = profile.name == "scout"

        for market, news, initial_score in candidates[:profile.max_trades_per_scan * 4]:
            if trades_executed >= profile.max_trades_per_scan:
                break

            question = market.get("question", "")

            # === STEP A: Run multi-strategy orchestrator (skip for Scout) ===
            if is_aggressive:
                # Scout fast path: trust initial score if it has any edge
                if abs(initial_score.edge) < profile.min_edge:
                    continue
                consensus = {
                    "should_trade": True,
                    "direction": initial_score.direction,
                    "agreeing_strategies": 1,
                    "consensus_reasoning": f"Scout fast-path: edge {initial_score.edge*100:.1f}%, sentiment {initial_score.news_sentiment:+.2f}",
                }
            else:
                orchestrator = StrategyOrchestrator()
                try:
                    consensus = await orchestrator.evaluate(
                        market, news,
                        min_agreeing=profile.min_strategies_agreeing,
                    )
                except Exception as e:
                    print(f"[{profile.display_name}] Strategy error: {e}")
                    await orchestrator.close()
                    continue
                await orchestrator.close()

                if not consensus["should_trade"]:
                    print(f"[{profile.display_name}] SKIP '{question[:40]}' - {consensus['consensus_reasoning'][:80]}")
                    continue

                print(f"[{profile.display_name}] CONSENSUS '{question[:40]}' - {consensus['agreeing_strategies']} strategies agree on {consensus['direction'].upper()}")

            # === STEP B: Deep multi-pass Claude validation (skip for Scout) ===
            llm_analysis = None
            verdict = "BUY"  # default for aggressive profiles

            if not is_aggressive and settings.anthropic_api_key:
                try:
                    analyst = DeepAnalyst()
                    llm_analysis = await analyst.full_analysis(market, news)
                    await analyst.close()
                except Exception as e:
                    print(f"[{profile.display_name}] LLM error: {e}")
                    continue

                if not llm_analysis:
                    continue

                # Claude must agree with strategy consensus
                if llm_analysis.get("direction") != consensus["direction"]:
                    print(f"[{profile.display_name}] SKIP '{question[:40]}' - Claude says {llm_analysis.get('direction')} but strategies say {consensus['direction']}")
                    continue

                # Profile-specific verdict check
                verdict = llm_analysis.get("final_verdict", "SKIP")
                if verdict not in profile.required_verdict:
                    print(f"[{profile.display_name}] SKIP '{question[:40]}' - verdict {verdict} not in {profile.required_verdict}")
                    continue

                # Pass consensus check
                if profile.require_pass_consensus:
                    p1 = llm_analysis.get("pass1_prob", 0.5)
                    p2 = llm_analysis.get("pass2_prob", 0.5)
                    p3 = llm_analysis.get("pass3_prob", 0.5)
                    if not ((p1 > 0.5 and p2 > 0.5 and p3 > 0.5) or (p1 < 0.5 and p2 < 0.5 and p3 < 0.5)):
                        print(f"[{profile.display_name}] SKIP '{question[:40]}' - pass consensus failed")
                        continue

                # Confidence check
                if llm_analysis["confidence"] < profile.min_claude_confidence:
                    print(f"[{profile.display_name}] SKIP '{question[:40]}' - confidence {llm_analysis['confidence']:.0%} < {profile.min_claude_confidence:.0%}")
                    continue

            # Re-score (with or without LLM)
            if llm_analysis:
                score = scorer.score_opportunity(
                    market, news,
                    llm_probability=llm_analysis["probability"],
                    llm_confidence=llm_analysis["confidence"],
                    llm_reasoning=llm_analysis.get("reasoning"),
                )
            else:
                score = initial_score

            # Final edge and score check
            if abs(score.edge) < profile.min_edge:
                print(f"[{profile.display_name}] SKIP '{question[:40]}' - edge {score.edge*100:.1f}% < {profile.min_edge*100:.0f}%")
                continue
            if score.score < profile.min_score:
                continue

            # Sentiment alignment check
            if profile.require_sentiment_alignment:
                if score.direction == "yes" and score.news_sentiment < 0:
                    print(f"[{profile.display_name}] SKIP '{question[:40]}' - sentiment misalignment")
                    continue
                if score.direction == "no" and score.news_sentiment > 0:
                    print(f"[{profile.display_name}] SKIP '{question[:40]}' - sentiment misalignment")
                    continue

            # Bet size from profile (capped at 10% of bankroll)
            size_usd = min(profile.bet_size_usd, bankroll * 0.10)
            if size_usd < 1.0:
                continue

            # Build reasoning combining Claude + Strategies
            if llm_analysis:
                reasoning = llm_analysis.get("reasoning", "")
                factors = llm_analysis.get("key_factors", [])
                if factors:
                    reasoning += " | Factors: " + ", ".join(factors[:3])
                reasoning += f" | Strategies({consensus['agreeing_strategies']}): {consensus['consensus_reasoning'][:200]}"
                devil = llm_analysis.get("devils_advocate", "")
                if devil:
                    reasoning += f" | Risk: {devil[:100]}"
                reasoning += f" | Verdict: {verdict}"
            else:
                # Scout fast path - no LLM
                reasoning = (
                    f"[SCOUT FAST] Edge {score.edge*100:+.1f}%, "
                    f"sentiment {score.news_sentiment:+.2f} across {score.news_count} articles, "
                    f"price {score.current_price*100:.0f}% → estimate {score.estimated_probability*100:.0f}%"
                )

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

            # Save trade with profile tag
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
                "profile": profile.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if storage:
                storage.save_trade(trade_data)
                if portfolio:
                    storage.update_portfolio({
                        "invested": portfolio["invested"] + size_usd,
                        "available": portfolio["available"] - size_usd,
                    }, profile=profile.name)

            await telegram.notify_trade(trade_data, llm_analysis)

            trades_executed += 1
            conf = llm_analysis["confidence"] if llm_analysis else score.confidence
            print(f"[{profile.display_name}] TRADE #{trades_executed}: {score.direction.upper()} '{question[:50]}' | Conf: {conf:.0%} | Edge: {score.edge*100:.1f}% | ${size_usd:.2f}")

            results.append({
                "question": question,
                "direction": score.direction,
                "edge": score.edge,
                "confidence": conf,
                "cost": size_usd,
                "verdict": verdict,
            })

        print(f"\n[{profile.display_name}] Done. {trades_executed} trades.")
        print(f"{'='*60}\n")

        return {
            "profile": profile.name,
            "display_name": profile.display_name,
            "scanned": len(all_markets),
            "filtered": len(markets),
            "candidates": len(candidates),
            "trades": trades_executed,
            "results": results,
        }

    finally:
        await poly_client.close()
        await pipeline.close()


async def run_all_profiles() -> dict:
    """Run scan for all 3 profiles in sequence."""
    results = {}
    for profile in all_profiles():
        try:
            results[profile.name] = await run_profile_scan(profile)
        except Exception as e:
            print(f"[Scanner] Error in {profile.name}: {e}")
            results[profile.name] = {"error": str(e)}
    return results


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
