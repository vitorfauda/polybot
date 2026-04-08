"""Auto-Resolver - Checks open trades and resolves them based on Polymarket data."""

import asyncio
from datetime import datetime, timezone
from dateutil import parser as date_parser
from services.polymarket.client import PolymarketClient
from services.storage import StorageService
from services.telegram_bot import TelegramAlert


async def resolve_open_trades() -> dict:
    """Check all open trades and resolve any that have been settled on Polymarket."""
    poly_client = PolymarketClient()
    telegram = TelegramAlert()
    try:
        storage = StorageService()
        storage._check()
    except:
        return {"error": "No storage"}

    resolved_count = 0
    results = []

    try:
        # Get all open trades
        trades = storage.get_trades(limit=200)
        open_trades = [t for t in trades if t.get("status") == "simulated"]

        print(f"[Resolver] Checking {len(open_trades)} open trades...")

        for trade in open_trades:
            try:
                market_id = trade.get("market_id")
                end_date_str = trade.get("end_date")
                if not market_id:
                    continue

                # Check if market has expired
                if end_date_str:
                    end_date = date_parser.parse(end_date_str)
                    if end_date.tzinfo is None:
                        end_date = end_date.replace(tzinfo=timezone.utc)
                    if end_date > datetime.now(timezone.utc):
                        continue  # not yet expired

                # Fetch latest market data from Polymarket
                try:
                    market_data = await poly_client.get_market(market_id)
                except:
                    continue

                # Check if resolved (closed=true and umaResolutionStatus or outcomePrices final)
                closed = market_data.get("closed", False)
                if not closed:
                    continue

                # Determine outcome from outcomePrices (after resolution: [1.0, 0.0] or [0.0, 1.0])
                import json as _json
                prices = market_data.get("outcomePrices", "[0.5,0.5]")
                if isinstance(prices, str):
                    try:
                        prices = _json.loads(prices)
                    except:
                        continue
                if not prices or len(prices) < 2:
                    continue

                price_yes = float(prices[0])
                price_no = float(prices[1])

                # Resolved if one price is 1.0
                if price_yes >= 0.99:
                    outcome = "yes"
                elif price_no >= 0.99:
                    outcome = "no"
                else:
                    continue  # not yet fully resolved

                # Calculate PnL
                direction = trade.get("direction", "yes")
                size = float(trade.get("size", 0))
                cost = float(trade.get("cost", 0))
                won = direction == outcome
                if won:
                    payout = size * 1.0  # $1 per share
                    pnl = payout - cost
                else:
                    payout = 0
                    pnl = -cost

                # Update trade
                storage.resolve_trade(trade["id"], outcome, round(pnl, 2))

                # Update portfolio for this profile
                profile = trade.get("profile", "default")
                portfolio = storage.get_portfolio(profile=profile)
                if portfolio:
                    storage.update_portfolio({
                        "invested": max(0, portfolio["invested"] - cost),
                        "available": portfolio["available"] + payout,
                        "total_pnl": portfolio["total_pnl"] + pnl,
                        "total_balance": portfolio["total_balance"] + pnl,
                        "win_count": portfolio["win_count"] + (1 if won else 0),
                        "loss_count": portfolio["loss_count"] + (0 if won else 1),
                    }, profile=profile)

                # Telegram notification
                await telegram.notify_resolution({
                    "question": trade.get("question", market_id),
                    "pnl": pnl,
                    "outcome": outcome,
                })

                resolved_count += 1
                results.append({
                    "id": trade["id"],
                    "question": trade.get("question", "")[:60],
                    "direction": direction,
                    "outcome": outcome,
                    "won": won,
                    "pnl": round(pnl, 2),
                    "profile": profile,
                })
                print(f"[Resolver] Resolved #{trade['id']} '{trade.get('question','')[:40]}' - {('WON' if won else 'LOST')} ${pnl:+.2f}")

            except Exception as e:
                print(f"[Resolver] Error resolving trade {trade.get('id')}: {e}")
                continue

        print(f"[Resolver] Resolved {resolved_count}/{len(open_trades)} trades")
        return {"resolved": resolved_count, "checked": len(open_trades), "results": results}

    finally:
        await poly_client.close()


async def run_resolver_loop(interval_minutes: int = 5):
    """Run resolver periodically."""
    while True:
        try:
            await resolve_open_trades()
        except Exception as e:
            print(f"[Resolver] Loop error: {e}")
        await asyncio.sleep(interval_minutes * 60)


if __name__ == "__main__":
    asyncio.run(resolve_open_trades())
