"""LLM-powered market analyst using Claude API for deep analysis."""

import json
from anthropic import AsyncAnthropic
from core.config import get_settings


class LLMAnalyst:
    """Uses Claude to deeply analyze prediction market opportunities."""

    def __init__(self):
        self.settings = get_settings()
        self.client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)

    async def analyze_market(
        self,
        market: dict,
        news_articles: list[dict],
        price_history: list[dict] | None = None,
        orderbook: dict | None = None,
    ) -> dict:
        """
        Deep analysis of a market using Claude.

        Returns:
            {
                "probability": float (0-1),
                "confidence": float (0-1),
                "direction": "yes" | "no",
                "reasoning": str,
                "key_factors": list[str],
                "risks": list[str],
                "time_sensitivity": "high" | "medium" | "low",
            }
        """
        question = market.get("question", "")
        current_price_yes = self._parse_price(market)
        volume = float(market.get("volume", 0))
        liquidity = float(market.get("liquidity", 0))
        end_date = market.get("endDate", "unknown")

        # Build news context
        news_context = ""
        if news_articles:
            news_items = []
            for a in news_articles[:10]:
                sentiment = a.get("sentiment_vader", 0)
                label = a.get("sentiment_label", "neutral")
                news_items.append(
                    f"- [{label} ({sentiment:+.2f})] {a['title']}"
                )
            news_context = "\n".join(news_items)
        else:
            news_context = "No recent news found for this market."

        # Build price history context
        price_context = ""
        if price_history and len(price_history) > 0:
            recent = price_history[-10:]
            prices_str = ", ".join([f"{p.get('p', 0):.2f}" for p in recent])
            price_context = f"Recent YES price trend (oldest to newest): {prices_str}"

        # Build orderbook context
        book_context = ""
        if orderbook:
            bids = orderbook.get("bids", [])[:3]
            asks = orderbook.get("asks", [])[:3]
            if bids:
                book_context += f"Top bids: {', '.join([f'${b.get('price',0)} x {b.get('size',0)}' for b in bids])}\n"
            if asks:
                book_context += f"Top asks: {', '.join([f'${a.get('price',0)} x {a.get('size',0)}' for a in asks])}"

        prompt = f"""You are an expert prediction market analyst. Analyze this market and provide your probability estimate.

## Market
Question: {question}
Current YES price: {current_price_yes:.2f} (implies {current_price_yes*100:.0f}% probability)
Volume: ${volume:,.0f}
Liquidity: ${liquidity:,.0f}
End date: {end_date}

## Recent News
{news_context}

## Price History
{price_context if price_context else "Not available"}

## Order Book
{book_context if book_context else "Not available"}

## Your Task
Analyze all available information and provide:
1. Your estimated TRUE probability (0.00 to 1.00) that the answer is YES
2. Your confidence in this estimate (0.00 to 1.00) - how certain you are
3. Key factors driving your estimate
4. Risks that could change the outcome
5. Time sensitivity - how quickly might the price move

IMPORTANT RULES:
- Be calibrated. If you're uncertain, your probability should reflect that.
- Consider base rates and historical precedents.
- News sentiment alone is not sufficient - analyze the substance.
- If the current market price seems efficient, say so.
- Be honest about your uncertainty level.

Respond ONLY with valid JSON in this exact format:
{{
    "probability": 0.XX,
    "confidence": 0.XX,
    "direction": "yes" or "no",
    "reasoning": "2-3 sentence summary of your analysis",
    "key_factors": ["factor 1", "factor 2", "factor 3"],
    "risks": ["risk 1", "risk 2"],
    "time_sensitivity": "high" or "medium" or "low"
}}"""

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip()
            # Extract JSON from response (handle markdown code blocks)
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)

            # Validate and clamp values
            result["probability"] = max(0.01, min(0.99, float(result.get("probability", 0.5))))
            result["confidence"] = max(0.1, min(1.0, float(result.get("confidence", 0.5))))
            if result["direction"] not in ("yes", "no"):
                result["direction"] = "yes" if result["probability"] > 0.5 else "no"

            return result

        except Exception as e:
            print(f"[LLMAnalyst] Error analyzing market: {e}")
            return {
                "probability": current_price_yes,
                "confidence": 0.2,
                "direction": "yes" if current_price_yes > 0.5 else "no",
                "reasoning": f"LLM analysis failed ({e}). Using market price as fallback.",
                "key_factors": ["Fallback to market price"],
                "risks": ["No AI analysis available"],
                "time_sensitivity": "low",
            }

    async def batch_analyze(
        self,
        markets: list[dict],
        news_by_market: dict[str, list[dict]],
        max_markets: int = 5,
    ) -> dict[str, dict]:
        """Analyze multiple markets. Returns {market_id: analysis}."""
        results = {}
        for market in markets[:max_markets]:
            market_id = market.get("conditionId", market.get("id", ""))
            news = news_by_market.get(market_id, [])
            analysis = await self.analyze_market(market, news)
            results[market_id] = analysis
        return results

    @staticmethod
    def _parse_price(market: dict) -> float:
        prices = market.get("outcomePrices", "[0.5,0.5]")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except:
                prices = [0.5, 0.5]
        return float(prices[0]) if prices else 0.5
