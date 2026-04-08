"""Master Analyst - The single most precise Claude analysis pipeline.

The user's insight: The other player uses Claude too. The difference is HOW.
This module focuses on extracting maximum precision from Claude through:

1. STRUCTURED DATA: Give Claude all relevant indicators in a clean format
2. CONSERVATIVE FRAMING: Force Claude to require high evidence before signaling
3. MULTI-STEP REASONING: Walk through analysis steps explicitly
4. UNCERTAINTY QUANTIFICATION: Make Claude rate its own confidence honestly
5. REJECTION BIAS: When in doubt, SKIP. We need 90%+ accuracy.
"""

import json
import httpx
from datetime import datetime, timezone
from anthropic import AsyncAnthropic
from core.config import get_settings


MASTER_PROMPT = """You are the Master Analyst for a prediction market trading system targeting 90%+ accuracy.

# YOUR MISSION
Decide if this is a HIGH-CONFIDENCE trading opportunity. If you're not extremely confident, you MUST SKIP. We trade selectively - we'd rather pass 100 marginal trades than take 1 wrong one.

# THE MARKET
Question: {question}
Resolves: {end_date} ({hours_left:.1f} hours from now)
Current YES price: {price_yes_pct}% (market's implied probability)
Current NO price: {price_no_pct}%
24h volume: ${volume:,.0f}
Liquidity: ${liquidity:,.0f}

# REAL DATA
{data_section}

# RECENT NEWS ({news_count} articles)
{news_section}

# YOUR ANALYTICAL FRAMEWORK

## Step 1: Base Rate
What's the historical base rate for this type of event? Think about similar past events.

## Step 2: Specific Evidence
What specific evidence makes THIS instance different from the base rate?
- Strong evidence FOR YES: [list]
- Strong evidence FOR NO: [list]

## Step 3: Time Analysis
Given {hours_left:.1f} hours remaining:
- Is there enough time for the event to develop?
- Are there any scheduled catalysts (events, announcements, deadlines)?

## Step 4: Market Efficiency Check
The market price is {price_yes_pct}% YES. Ask yourself:
- WHY hasn't the market already corrected this?
- If you see an "edge", it usually means YOU are missing something the market knows
- Only trade if you have a SPECIFIC reason for the inefficiency (recent news the market missed, unusual whale activity, etc.)

## Step 5: Confidence Calibration
Rate your confidence:
- 95%+ confident: STRONG_BUY (this is rare - maybe 1 in 100 markets)
- 85-94% confident: BUY
- 70-84% confident: HOLD (interesting but not actionable)
- Below 70%: SKIP

## Step 6: Devil's Advocate
Before submitting, argue against your own conclusion. If the counter-argument is strong, lower your confidence.

# RESPONSE FORMAT
Respond ONLY with this JSON structure:

```json
{{
  "step1_base_rate": "Your base rate analysis (1 sentence)",
  "step2_evidence_for": ["evidence point 1", "evidence point 2"],
  "step2_evidence_against": ["counter point 1", "counter point 2"],
  "step3_time_analysis": "Time-based reasoning (1 sentence)",
  "step4_market_check": "Why might the market be wrong here? (1 sentence)",
  "step5_probability": 0.XX,
  "step5_confidence": 0.XX,
  "step6_devils_advocate": "Strongest counter to your view (1 sentence)",
  "direction": "yes" or "no",
  "verdict": "STRONG_BUY" or "BUY" or "HOLD" or "SKIP",
  "key_reason": "ONE sentence summarizing why this is or isn't a trade",
  "risk_level": "low" or "medium" or "high"
}}
```

# CRITICAL RULES
- If evidence is MIXED, verdict must be SKIP or HOLD
- If you can't articulate WHY the market is wrong, verdict must be SKIP
- If hours_left < 2, raise your confidence requirement (less time to be right)
- If volume is below $500, the market is illiquid - require very high confidence
- Default to SKIP. The cost of a bad trade is much higher than the cost of missing one.
"""


class MasterAnalyst:
    """Single high-precision Claude analyst."""

    def __init__(self):
        settings = get_settings()
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None

    async def analyze(
        self,
        market: dict,
        news: list[dict],
        crypto_data: dict | None = None,
        whale_data: dict | None = None,
    ) -> dict:
        """
        Run the master analysis. Returns a structured verdict.
        """
        if not self.client:
            return {"error": "No Claude API", "verdict": "SKIP"}

        from dateutil import parser as date_parser

        question = market.get("question", "")
        end_date_str = market.get("endDate", "unknown")
        try:
            end_date = date_parser.parse(end_date_str)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            hours_left = (end_date - datetime.now(timezone.utc)).total_seconds() / 3600
        except:
            hours_left = 999

        # Parse prices
        prices = market.get("outcomePrices", "[0.5,0.5]")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except:
                prices = [0.5, 0.5]
        price_yes = float(prices[0]) if prices else 0.5
        price_no = float(prices[1]) if len(prices) > 1 else 0.5

        volume = float(market.get("volume", 0))
        liquidity = float(market.get("liquidity", 0))

        # Build data section
        data_lines = []
        if crypto_data:
            ca = crypto_data.get("analysis", {})
            data_lines.append(f"## Cryptocurrency Data")
            data_lines.append(f"- Coin: {crypto_data.get('coin', '?').upper()}")
            data_lines.append(f"- Current price: ${ca.get('current_price', 0):,.2f}")
            data_lines.append(f"- 24h change: {ca.get('price_change_24h', 0):+.2f}%")
            data_lines.append(f"- 7d change: {ca.get('price_change_7d', 0):+.2f}%")
            rsi = ca.get('rsi')
            if rsi:
                data_lines.append(f"- RSI(14): {rsi:.1f} ({'overbought' if rsi > 70 else 'oversold' if rsi < 30 else 'neutral'})")
            data_lines.append(f"- Technical signal: {ca.get('technical_signal', 'neutral')}")
            if ca.get('target_price'):
                data_lines.append(f"- Target price: ${ca['target_price']:,.2f}")
                data_lines.append(f"- Distance to target: {ca.get('distance_to_target_pct', 0):+.1f}%")

        if whale_data:
            data_lines.append(f"\n## Whale Activity (Polymarket)")
            data_lines.append(f"- Recent large trades: {whale_data.get('summary', 'N/A')}")

        data_section = "\n".join(data_lines) if data_lines else "No additional structured data available."

        # Build news section
        news_section = ""
        if news:
            news_lines = []
            for i, a in enumerate(news[:6], 1):
                sentiment = a.get("sentiment_vader", 0)
                sentiment_label = "POS" if sentiment > 0.05 else "NEG" if sentiment < -0.05 else "NEU"
                news_lines.append(f"{i}. [{sentiment_label}] {a['title']}")
            news_section = "\n".join(news_lines)
        else:
            news_section = "No relevant news found in the last 24 hours."

        # Format prompt
        prompt = MASTER_PROMPT.format(
            question=question,
            end_date=end_date_str,
            hours_left=hours_left,
            price_yes_pct=int(price_yes * 100),
            price_no_pct=int(price_no * 100),
            volume=volume,
            liquidity=liquidity,
            data_section=data_section,
            news_count=len(news),
            news_section=news_section,
        )

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)

            # Validate and clamp
            result["probability"] = max(0.01, min(0.99, float(result.get("step5_probability", 0.5))))
            result["confidence"] = max(0.0, min(1.0, float(result.get("step5_confidence", 0.5))))

            # Compute edge
            direction = result.get("direction", "yes")
            if direction == "yes":
                result["edge"] = result["probability"] - price_yes
            else:
                result["edge"] = (1 - result["probability"]) - price_no

            # Final guardrails - force conservative behavior
            verdict = result.get("verdict", "SKIP")
            if result["confidence"] < 0.85 and verdict in ("STRONG_BUY", "BUY"):
                result["verdict"] = "HOLD"
                result["downgrade_reason"] = f"Confidence {result['confidence']:.0%} below 85% threshold"

            # If hours_left < 2, require even higher confidence
            if hours_left < 2 and result["confidence"] < 0.90 and result["verdict"] == "BUY":
                result["verdict"] = "HOLD"
                result["downgrade_reason"] = f"Only {hours_left:.1f}h left, need 90%+ confidence"

            # If volume is very low, skip unless ultra-high confidence
            if volume < 500 and result["confidence"] < 0.92:
                result["verdict"] = "SKIP"
                result["downgrade_reason"] = f"Low volume ${volume:.0f} requires 92%+ confidence"

            return result

        except Exception as e:
            return {
                "error": str(e),
                "verdict": "SKIP",
                "confidence": 0,
                "probability": price_yes,
                "direction": "yes",
                "key_reason": f"Analysis failed: {e}",
            }
