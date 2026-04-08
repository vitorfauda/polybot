"""Multi-Profile Continuous Loop.

Runs all 3 main profiles (Hunter/Sniper/Scout) in a continuous loop
to compare their performance over time.

Resolves expired trades automatically every cycle.
"""

import asyncio
from datetime import datetime, timezone
from services.profiles import HUNTER, SNIPER, SCOUT
from workers.auto_scanner import run_profile_scan
from workers.auto_resolver import resolve_open_trades


async def multi_profile_loop(interval_seconds: int = 300):
    """Run all 3 profiles every interval_seconds (default 5 min)."""
    print(f"\n{'='*70}")
    print(f"[MultiLoop] Starting 3-profile comparison loop")
    print(f"[MultiLoop] Interval: {interval_seconds}s")
    print(f"[MultiLoop] Profiles: Hunter (conservador), Sniper (medio), Scout (agressivo)")
    print(f"{'='*70}\n")

    cycle = 0
    while True:
        try:
            cycle += 1
            print(f"\n>>> CYCLE {cycle} @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} <<<")

            # 1. Resolve expired trades first
            try:
                resolved = await resolve_open_trades()
                if resolved.get("resolved", 0) > 0:
                    print(f"[MultiLoop] Resolved {resolved['resolved']} expired trades")
            except Exception as e:
                print(f"[MultiLoop] Resolver error: {e}")

            # 2. Run each profile in sequence
            for profile in [HUNTER, SNIPER, SCOUT]:
                try:
                    result = await run_profile_scan(profile)
                    print(f"[MultiLoop] {profile.display_name}: {result.get('trades', 0)} trades from {result.get('candidates', 0)} candidates")
                except Exception as e:
                    print(f"[MultiLoop] {profile.display_name} ERROR: {e}")
                # Small pause between profiles
                await asyncio.sleep(2)

            print(f"[MultiLoop] Cycle {cycle} complete. Sleeping {interval_seconds}s...")

        except Exception as e:
            print(f"[MultiLoop] Cycle error: {e}")

        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    import sys
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    asyncio.run(multi_profile_loop(interval_seconds=interval))
