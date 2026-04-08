"""Feedback Loop - Learns from past trades to improve future analysis."""

from anthropic import AsyncAnthropic
from core.config import get_settings
import json


class FeedbackEngine:
    """Analyzes past trade results to extract lessons and improve future predictions."""

    def __init__(self):
        settings = get_settings()
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def analyze_trade_result(self, trade: dict, market_outcome: str) -> dict:
        """
        After a trade resolves, analyze what went right or wrong.

        Returns:
            {
                "correct": bool,
                "lesson": str,
                "pattern": str,
                "confidence_calibration": str,
                "should_adjust": str,
            }
        """
        won = trade.get("direction") == market_outcome
        pnl = trade.get("pnl", 0)
        question = trade.get("question", "Unknown")
        direction = trade.get("direction", "?")
        price = trade.get("price", 0)
        edge = trade.get("edge", 0)
        reasoning = trade.get("reasoning", "No reasoning recorded")

        prompt = f"""You are improving an AI prediction market trading system. A trade just resolved. Analyze what happened.

## Trade Details
- Market: {question}
- Our bet: {direction.upper()} at {price*100:.0f}% implied probability
- Our estimated edge: {edge*100:.1f}%
- Actual outcome: {market_outcome.upper()}
- Result: {"WON" if won else "LOST"} (PnL: ${pnl:+.2f})
- Original reasoning: {reasoning}

## Your Task
Analyze this result and extract actionable lessons:
1. Was our reasoning sound even if we lost? (bad luck vs bad analysis)
2. What pattern or signal did we miss or correctly identify?
3. How should we adjust our confidence calibration?
4. What specific rule should we add/modify for future trades?

Respond ONLY with JSON:
{{
    "correct": {str(won).lower()},
    "lesson": "1-2 sentence lesson learned",
    "pattern": "pattern identified (e.g., 'sports underdog bets at <5% rarely hit')",
    "confidence_calibration": "over_confident" or "under_confident" or "well_calibrated",
    "adjustment_rule": "specific rule to apply going forward"
}}"""

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except Exception as e:
            return {
                "correct": won,
                "lesson": f"Analysis failed: {e}",
                "pattern": "unknown",
                "confidence_calibration": "unknown",
                "adjustment_rule": "none",
            }

    async def get_lessons_summary(self, past_results: list[dict]) -> str:
        """
        Summarize lessons from multiple past trades for use in future analysis.
        This gets injected into the LLM analyst prompt.
        """
        if not past_results:
            return ""

        wins = [r for r in past_results if r.get("pnl", 0) > 0]
        losses = [r for r in past_results if r.get("pnl", 0) < 0]

        summary_parts = []
        if wins:
            summary_parts.append(f"Won {len(wins)} trades. Patterns that worked: trades with high news sentiment alignment.")
        if losses:
            loss_reasons = []
            for l in losses[:5]:
                q = l.get("question", "?")[:50]
                loss_reasons.append(f"- Lost on '{q}' (direction: {l.get('direction')}, edge: {l.get('edge', 0)*100:.1f}%)")
            summary_parts.append(f"Lost {len(losses)} trades:\n" + "\n".join(loss_reasons))

        total_pnl = sum(r.get("pnl", 0) for r in past_results if r.get("pnl"))
        win_rate = len(wins) / len(past_results) * 100 if past_results else 0
        summary_parts.append(f"Overall: {win_rate:.0f}% win rate, ${total_pnl:+.2f} PnL")

        return "\n".join(summary_parts)

    async def generate_rules_from_history(self, past_results: list[dict]) -> list[str]:
        """Generate trading rules based on historical performance."""
        if len(past_results) < 5:
            return ["Not enough data to generate rules yet."]

        wins = [r for r in past_results if r.get("pnl", 0) > 0]
        losses = [r for r in past_results if r.get("pnl", 0) <= 0]

        prompt = f"""Based on these trading results, generate 3-5 specific rules:

Wins ({len(wins)}): Average edge {sum(w.get('edge',0) for w in wins)/len(wins)*100:.1f}% when available
Losses ({len(losses)}): Average edge {sum(l.get('edge',0) for l in losses)/len(losses)*100:.1f}% when available

Categories won: {', '.join(set(w.get('category','?') for w in wins[:10]))}
Categories lost: {', '.join(set(l.get('category','?') for l in losses[:10]))}

Win rate: {len(wins)/len(past_results)*100:.0f}%

Generate specific, actionable rules as a JSON array of strings."""

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except:
            return ["Minimum 10% edge for any trade", "Avoid markets expiring in <2 hours"]
