"""HFT Crypto Scanner - Short-term crypto market trading bot.

Implements the user's microstructure framework:
1. Filter to crypto markets with adequate liquidity
2. Read order book and compute microstructure signals (queue imbalance, microprice)
3. Validate with Master Analyst (Claude) for final go/no-go
4. Execute trades only when ALL signals align
5. Loop continuously for short-term opportunities

Target: 90%+ accuracy through extreme selectivity.
"""

import asyncio
import json
from datetime import datetime, timezone
from dateutil import parser as date_parser
from services.polymarket.client import PolymarketClient
from services.news.pipeline import NewsPipeline
from services.analysis.microstructure import (
    PolymarketBookReader,
    analyze_book,
    confidence_after_costs,
)
from services.analysis.master_analyst import MasterAnalyst
from services.storage import StorageService
from services.telegram_bot import TelegramAlert
from core.config import get_settings


CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
    "xrp", "ripple", "cardano", "ada", "dogecoin", "doge",
]


def is_crypto(market: dict) -> bool:
    q = market.get("question", "").lower()
    return any(c in q for c in CRYPTO_KEYWORDS)


async def hft_scan_cycle(
    bet_size: float = 5.0,
    min_volume: float = 1000,
    min_confidence: float = 0.85,
    min_net_edge: float = 0.02,
    max_trades: int = 2,
    profile_name: str = "crypto_hunter",
    dry_run: bool = False,
) -> dict:
    """
    Run one HFT scan cycle on crypto markets.

    Args:
        bet_size: Fixed bet size in USD (small for high-frequency)
        min_volume: Minimum market volume to consider
        min_confidence: Minimum Claude confidence to trade
        min_net_edge: Minimum edge after fees
        max_trades: Max trades to execute per cycle
        profile_name: Portfolio profile to use
        dry_run: If True, analyze but don't execute
    """
    settings = get_settings()
    poly = PolymarketClient()
    book_reader = PolymarketBookReader()
    news_pipeline = NewsPipeline()
    master = MasterAnalyst()
    telegram = TelegramAlert()

    storage = None
    try:
        storage = StorageService()
        storage._check()
    except:
        pass

    cycle_start = datetime.now(timezone.utc)
    print(f"\n{'='*70}")
    print(f"[HFT Crypto] Cycle start: {cycle_start.strftime('%H:%M:%S UTC')}")
    print(f"{'='*70}")

    try:
        # 1. Fetch markets
        all_markets = await poly.get_active_markets(limit=200)

        # 2. Filter to crypto with volume
        candidates = []
        for m in all_markets:
            if not is_crypto(m):
                continue
            volume = float(m.get("volume", 0))
            if volume < min_volume:
                continue
            candidates.append(m)

        candidates.sort(key=lambda m: float(m.get("volume", 0)), reverse=True)
        print(f"[HFT Crypto] {len(candidates)} crypto markets with volume >= ${min_volume}")

        # 3. Microstructure analysis on each
        signal_candidates = []
        for market in candidates[:20]:  # cap to top 20 by volume
            token_ids = market.get("clobTokenIds", "[]")
            if isinstance(token_ids, str):
                try:
                    token_ids = json.loads(token_ids)
                except:
                    continue
            if not token_ids:
                continue

            snap = await book_reader.get_book(token_ids[0])
            if not snap:
                continue

            signals = analyze_book(snap)

            if not signals.eligible:
                continue

            if signals.confidence < 0.6:
                continue

            signal_candidates.append({
                "market": market,
                "snapshot": snap,
                "signals": signals,
                "yes_token": token_ids[0],
                "no_token": token_ids[1] if len(token_ids) > 1 else None,
            })

        print(f"[HFT Crypto] {len(signal_candidates)} markets passed microstructure filters")

        # 4. Master Analyst validation on top candidates
        results = []
        trades_executed = 0

        # Sort by signal confidence
        signal_candidates.sort(key=lambda c: c["signals"].confidence, reverse=True)

        for cand in signal_candidates[:5]:
            if trades_executed >= max_trades:
                break

            market = cand["market"]
            snap = cand["snapshot"]
            signals = cand["signals"]
            question = market.get("question", "")

            print(f"\n[HFT Crypto] Analyzing: {question[:70]}")
            print(f"  Microstructure: {signals.direction_signal} ({signals.confidence:.0%}) | QI: {signals.queue_imbalance:+.2f} | Micro: {signals.microprice:.3f}")

            # Get news
            try:
                news = await news_pipeline.collect_for_market(question, max_results=3)
            except:
                news = []

            # Build whale data summary from microstructure
            whale_data = {
                "summary": f"Top of book: bid ${snap.best_bid:.3f}x{snap.bid_size:.0f} / ask ${snap.best_ask:.3f}x{snap.ask_size:.0f}, QI={signals.queue_imbalance:+.2f}",
            }

            # Run Master Analyst
            master_result = await master.analyze(market, news, whale_data=whale_data)

            verdict = master_result.get("verdict", "SKIP")
            confidence = master_result.get("confidence", 0)
            edge = master_result.get("edge", 0)
            direction = master_result.get("direction", "yes")

            print(f"  Master: {verdict} | Conf: {confidence:.0%} | Edge: {edge*100:+.1f}% | Dir: {direction.upper()}")
            print(f"  Reason: {master_result.get('key_reason', '')[:120]}")

            # Decision criteria - all must align
            if verdict not in ("STRONG_BUY", "BUY"):
                print(f"  SKIP: verdict {verdict}")
                continue

            if confidence < min_confidence:
                print(f"  SKIP: confidence {confidence:.0%} < {min_confidence:.0%}")
                continue

            # Microstructure must agree with Master Analyst direction
            ms_direction = signals.direction_signal
            if ms_direction == "bullish" and direction != "yes":
                print(f"  SKIP: microstructure says bullish but Master says {direction}")
                continue
            if ms_direction == "bearish" and direction != "no":
                print(f"  SKIP: microstructure says bearish but Master says {direction}")
                continue

            # Check net edge after fees
            net_conf, profitable = confidence_after_costs(confidence, edge, fee_pct=0.018)
            if not profitable:
                print(f"  SKIP: not profitable after fees (net conf: {net_conf:.0%})")
                continue

            if abs(edge) < min_net_edge:
                print(f"  SKIP: edge {abs(edge)*100:.1f}% < min {min_net_edge*100:.1f}%")
                continue

            # All checks passed - EXECUTE
            print(f"  ✓ ALL CHECKS PASSED - EXECUTING TRADE")

            price = snap.best_bid if direction == "yes" else (1 - snap.best_ask)
            # Use mid for entry estimate
            entry_price = snap.mid_price if direction == "yes" else (1 - snap.mid_price)

            # Build comprehensive reasoning
            reasoning = (
                f"[HFT-MICROSTRUCTURE] {master_result.get('key_reason', '')[:200]} | "
                f"QI: {signals.queue_imbalance:+.2f}, Microprice: {signals.microprice:.3f}, "
                f"Spread: ${snap.spread:.4f}, Bid/Ask sizes: {snap.bid_size:.0f}/{snap.ask_size:.0f} | "
                f"Master verdict: {verdict} ({confidence:.0%} conf)"
            )

            trade_data = {
                "market_id": market.get("conditionId", market.get("id", "")),
                "question": question,
                "side": "buy",
                "direction": direction,
                "price": entry_price,
                "size": bet_size / entry_price if entry_price > 0 else 0,
                "cost": bet_size,
                "status": "simulated",
                "edge": edge,
                "end_date": market.get("endDate"),
                "reasoning": reasoning,
                "profile": profile_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if not dry_run:
                if storage:
                    storage.save_trade(trade_data)
                    portfolio = storage.get_portfolio(profile=profile_name)
                    if portfolio:
                        storage.update_portfolio({
                            "invested": portfolio["invested"] + bet_size,
                            "available": portfolio["available"] - bet_size,
                        }, profile=profile_name)

                await telegram.notify_trade(trade_data, master_result)

            trades_executed += 1
            results.append({
                "question": question,
                "direction": direction,
                "edge": edge,
                "confidence": confidence,
                "verdict": verdict,
                "qi": signals.queue_imbalance,
                "microprice": signals.microprice,
                "cost": bet_size,
                "reasoning": master_result.get("key_reason", ""),
            })

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        print(f"\n[HFT Crypto] Cycle done in {elapsed:.1f}s. {trades_executed} trades executed.")
        print(f"{'='*70}")

        return {
            "cycle_time": elapsed,
            "markets_scanned": len(all_markets),
            "crypto_with_volume": len(candidates),
            "passed_microstructure": len(signal_candidates),
            "trades_executed": trades_executed,
            "results": results,
        }

    finally:
        await poly.close()
        await book_reader.close()
        await news_pipeline.close()


async def hft_loop(interval_seconds: int = 60, **kwargs):
    """Run HFT scanner continuously."""
    print(f"[HFT Loop] Starting continuous scan every {interval_seconds}s")
    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            print(f"\n>>> CYCLE {cycle_count} <<<")
            await hft_scan_cycle(**kwargs)
        except Exception as e:
            print(f"[HFT Loop] Error in cycle: {e}")
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    import sys
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    asyncio.run(hft_loop(interval_seconds=interval))
