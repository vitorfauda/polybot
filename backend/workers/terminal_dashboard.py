"""Terminal Dashboard - Live updating CLI pipeline for PolyBot.

Beautiful terminal UI with real-time updates showing:
- Pipeline status (idle/scanning/analyzing/trading)
- Scan cycle counter
- Markets scanned, headlines found, signals generated
- Performance per profile (PnL, win rate)
- Recent trades with details
- Market odds being analyzed
"""

import asyncio
import os
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

from services.storage import StorageService
from services.profiles import all_profiles
from workers.auto_scanner import run_profile_scan, _hours_until
from workers.auto_resolver import resolve_open_trades

console = Console()


class PipelineState:
    def __init__(self):
        self.status = "idle"
        self.cycle = 0
        self.markets_scanned = 0
        self.headlines_found = 0
        self.signals_generated = 0
        self.last_scan_at = None
        self.current_market = ""
        self.current_profile = ""
        self.recent_logs = []  # last 10 log lines
        self.recent_trades = []  # last analyses

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.recent_logs.append(f"[{ts}] {msg}")
        if len(self.recent_logs) > 10:
            self.recent_logs.pop(0)

    def add_trade(self, trade: dict):
        self.recent_trades.append(trade)
        if len(self.recent_trades) > 20:
            self.recent_trades.pop(0)


def make_header(state: PipelineState) -> Panel:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    title = Text()
    title.append("⚡ POLYBOT ", style="bold yellow")
    title.append("// ", style="dim")
    title.append("AI Prediction Market Pipeline", style="bold cyan")
    title.append(f"   {now}", style="dim white")
    return Panel(Align.center(title), border_style="yellow", box=box.DOUBLE)


def make_status_panel(state: PipelineState) -> Panel:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="cyan", width=20)
    table.add_column()

    status_color = {
        "idle": "dim white",
        "scanning": "bold yellow",
        "analyzing": "bold cyan",
        "trading": "bold green",
        "resolving": "bold magenta",
    }.get(state.status, "white")

    table.add_row("Pipeline", Text(state.status.upper(), style=status_color))
    table.add_row("Scan Cycle", str(state.cycle))
    table.add_row("Markets Scanned", str(state.markets_scanned))
    table.add_row("Headlines Found", str(state.headlines_found))
    table.add_row("Signals/Trades", str(state.signals_generated))
    if state.current_profile:
        table.add_row("Current Profile", Text(state.current_profile, style="bold magenta"))
    if state.current_market:
        table.add_row("Current Market", state.current_market[:50])
    if state.last_scan_at:
        table.add_row("Last Scan", state.last_scan_at)

    return Panel(table, title="[bold]PIPELINE STATUS[/bold]", border_style="cyan", box=box.ROUNDED)


def make_performance_panel(storage) -> Panel:
    """Show performance for all profiles."""
    table = Table(box=box.SIMPLE, header_style="bold magenta")
    table.add_column("Profile", style="bold")
    table.add_column("Balance", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("W/L", justify="right")
    table.add_column("Win Rate", justify="right")

    if not storage:
        table.add_row("DB offline", "-", "-", "-", "-", "-")
        return Panel(table, title="[bold]PERFORMANCE[/bold]", border_style="green", box=box.ROUNDED)

    try:
        portfolios = storage.get_all_portfolios()
        for profile in all_profiles():
            p = next((x for x in portfolios if x.get("profile") == profile.name), None)
            if not p:
                continue
            balance = p.get("total_balance", 0)
            pnl = p.get("total_pnl", 0)
            wins = p.get("win_count", 0)
            losses = p.get("loss_count", 0)
            total = wins + losses

            try:
                trades = storage.get_trades(limit=100, profile=profile.name)
                trade_count = len(trades)
            except:
                trade_count = total

            win_rate = (wins / total * 100) if total > 0 else 0

            pnl_style = "green" if pnl >= 0 else "red"
            wr_style = "green" if win_rate >= 90 else ("yellow" if win_rate >= 70 else "white")

            table.add_row(
                profile.display_name,
                f"${balance:,.2f}",
                Text(f"{pnl:+,.2f}", style=pnl_style),
                str(trade_count),
                f"{wins}/{losses}",
                Text(f"{win_rate:.0f}%", style=wr_style),
            )
    except Exception as e:
        table.add_row(f"Error: {str(e)[:40]}", "-", "-", "-", "-", "-")

    return Panel(table, title="[bold]PERFORMANCE[/bold]", border_style="green", box=box.ROUNDED)


def make_trades_panel(storage) -> Panel:
    """Show recent trades across all profiles."""
    table = Table(box=box.SIMPLE, header_style="bold magenta", expand=True)
    table.add_column("ID", width=4)
    table.add_column("Profile", width=14)
    table.add_column("Side", width=4, justify="center")
    table.add_column("Question", overflow="ellipsis", no_wrap=True)
    table.add_column("Price", width=7, justify="right")
    table.add_column("Edge", width=7, justify="right")
    table.add_column("Status", width=10, justify="center")
    table.add_column("PnL", width=10, justify="right")

    if not storage:
        return Panel(table, title="[bold]RECENT TRADES[/bold]", border_style="blue", box=box.ROUNDED)

    try:
        trades = storage.get_trades(limit=15)
        for t in trades:
            tid = t.get("id", "?")
            profile = t.get("profile") or "default"
            side = t.get("direction", "?").upper()
            side_style = "green" if side == "YES" else "red"
            q = (t.get("question") or t.get("market_id", ""))[:60]
            price = t.get("price", 0)
            edge = t.get("edge", 0) or 0
            status = t.get("status", "?")
            pnl = t.get("pnl")

            status_style = {
                "won": "bold green",
                "lost": "bold red",
                "simulated": "yellow",
                "default": "white",
            }.get(status, "white")

            pnl_str = f"{pnl:+.2f}" if pnl is not None else "-"
            pnl_style = "green" if pnl and pnl > 0 else ("red" if pnl and pnl < 0 else "dim")

            table.add_row(
                str(tid),
                profile,
                Text(side, style=side_style),
                q,
                f"{price*100:.0f}%",
                f"{edge*100:+.1f}%" if edge else "-",
                Text(status, style=status_style),
                Text(pnl_str, style=pnl_style),
            )
    except Exception as e:
        table.add_row("ERR", str(e)[:30], "-", "-", "-", "-", "-", "-")

    return Panel(table, title="[bold]RECENT TRADES[/bold]", border_style="blue", box=box.ROUNDED)


def make_logs_panel(state: PipelineState) -> Panel:
    text = Text()
    for log in state.recent_logs[-8:]:
        if "TRADE" in log or "EXECUTED" in log:
            text.append(log + "\n", style="bold green")
        elif "SKIP" in log:
            text.append(log + "\n", style="dim yellow")
        elif "ERROR" in log or "Error" in log:
            text.append(log + "\n", style="red")
        elif "CONSENSUS" in log:
            text.append(log + "\n", style="cyan")
        else:
            text.append(log + "\n", style="white")
    return Panel(text, title="[bold]LIVE LOG[/bold]", border_style="magenta", box=box.ROUNDED)


def make_layout(state: PipelineState, storage) -> Layout:
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=2),
    )
    layout["left"].split(
        Layout(name="status"),
        Layout(name="performance"),
    )
    layout["right"].split(
        Layout(name="trades", ratio=2),
        Layout(name="logs", ratio=1),
    )

    layout["header"].update(make_header(state))
    layout["status"].update(make_status_panel(state))
    layout["performance"].update(make_performance_panel(storage))
    layout["trades"].update(make_trades_panel(storage))
    layout["logs"].update(make_logs_panel(state))

    return layout


async def run_dashboard(scan_interval: int = 600):
    """
    Main dashboard loop. Runs scans periodically and shows live updates.

    Args:
        scan_interval: seconds between scan cycles (default 10 min)
    """
    state = PipelineState()
    state.log("Pipeline initialized")

    try:
        storage = StorageService()
        storage._check()
        state.log("Connected to Supabase")
    except Exception as e:
        storage = None
        state.log(f"Storage error: {e}")

    with Live(make_layout(state, storage), refresh_per_second=2, screen=True) as live:
        # Initial render
        await asyncio.sleep(1)
        live.update(make_layout(state, storage))

        while True:
            try:
                state.cycle += 1
                state.last_scan_at = datetime.now().strftime("%H:%M:%S")

                # === Resolve any expired trades first ===
                state.status = "resolving"
                state.log(f"Cycle {state.cycle}: resolving open trades...")
                live.update(make_layout(state, storage))
                try:
                    resolved = await resolve_open_trades()
                    if resolved.get("resolved", 0) > 0:
                        state.log(f"Resolved {resolved['resolved']} trades")
                except Exception as e:
                    state.log(f"Resolver error: {e}")

                # === Run scans for each profile ===
                for profile in all_profiles():
                    state.status = "scanning"
                    state.current_profile = profile.display_name
                    state.log(f"Scanning {profile.display_name}...")
                    live.update(make_layout(state, storage))

                    try:
                        result = await run_profile_scan(profile)
                        state.markets_scanned = result.get("scanned", 0)
                        state.signals_generated += result.get("trades", 0)
                        if result.get("trades", 0) > 0:
                            state.log(f"{profile.display_name}: {result['trades']} TRADES")
                        else:
                            state.log(f"{profile.display_name}: 0 trades ({result.get('candidates', 0)} candidates)")
                    except Exception as e:
                        state.log(f"{profile.display_name} error: {str(e)[:60]}")

                    live.update(make_layout(state, storage))
                    await asyncio.sleep(2)

                state.current_profile = ""
                state.status = "idle"
                state.log(f"Cycle {state.cycle} complete. Next in {scan_interval}s.")
                live.update(make_layout(state, storage))

                # Wait for next cycle while updating display
                for _ in range(scan_interval):
                    await asyncio.sleep(1)
                    live.update(make_layout(state, storage))

            except KeyboardInterrupt:
                state.log("Shutting down...")
                live.update(make_layout(state, storage))
                break
            except Exception as e:
                state.log(f"Loop error: {str(e)[:80]}")
                live.update(make_layout(state, storage))
                await asyncio.sleep(30)


if __name__ == "__main__":
    import sys
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    try:
        asyncio.run(run_dashboard(scan_interval=interval))
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped[/yellow]")
