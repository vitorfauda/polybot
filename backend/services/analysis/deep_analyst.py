"""Deep Multi-Pass Analyst - Uses Claude with web search and multiple analysis rounds."""

import json
import httpx
import feedparser
from anthropic import AsyncAnthropic
from core.config import get_settings


class DeepAnalyst:
    """
    Multi-pass analysis system:
    Pass 1: Quick filter (sentiment + basic Claude)
    Pass 2: Deep research (web search + detailed Claude)
    Pass 3: Devil's advocate (challenge the thesis)
    """

    def __init__(self):
        settings = get_settings()
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._http = httpx.AsyncClient(timeout=15.0)

    async def full_analysis(
        self,
        market: dict,
        news_articles: list[dict],
        past_lessons: str = "",
        price_history: list[dict] | None = None,
    ) -> dict:
        """
        Run full 3-pass analysis pipeline.

        Returns:
            {
                "probability": float,
                "confidence": float,
                "direction": "yes" | "no",
                "reasoning": str,
                "key_factors": list[str],
                "risks": list[str],
                "web_research": str,
                "devils_advocate": str,
                "final_verdict": str,
                "pass1_prob": float,
                "pass2_prob": float,
                "pass3_prob": float,
            }
        """
        question = market.get("question", "")
        current_price = self._parse_price(market)

        # === PASS 1: Quick Analysis ===
        pass1 = await self._pass1_quick(market, news_articles, past_lessons)
        print(f"[DeepAnalyst] Pass 1: {pass1['probability']:.0%} confidence={pass1['confidence']:.0%} ({pass1['direction']})")

        # If Pass 1 confidence is very low, skip deeper analysis
        if pass1["confidence"] < 0.2:
            return {**pass1, "pass1_prob": pass1["probability"], "pass2_prob": pass1["probability"], "pass3_prob": pass1["probability"]}

        # === PASS 2: Deep Research with Web Search ===
        web_context = await self._web_research(question)
        pass2 = await self._pass2_deep(market, news_articles, web_context, pass1, past_lessons)
        print(f"[DeepAnalyst] Pass 2: {pass2['probability']:.0%} confidence={pass2['confidence']:.0%}")

        # === PASS 3: Devil's Advocate ===
        pass3 = await self._pass3_devils_advocate(market, pass2)
        print(f"[DeepAnalyst] Pass 3 (final): {pass3['probability']:.0%} confidence={pass3['confidence']:.0%}")

        return {
            "probability": pass3["probability"],
            "confidence": pass3["confidence"],
            "direction": pass3["direction"],
            "reasoning": pass3["reasoning"],
            "key_factors": pass2.get("key_factors", []),
            "risks": pass3.get("risks", []),
            "web_research": web_context[:500],
            "devils_advocate": pass3.get("counter_argument", ""),
            "final_verdict": pass3.get("final_verdict", ""),
            "pass1_prob": pass1["probability"],
            "pass2_prob": pass2["probability"],
            "pass3_prob": pass3["probability"],
        }

    async def _pass1_quick(self, market: dict, news: list[dict], lessons: str) -> dict:
        """Pass 1: Quick analysis with news sentiment."""
        question = market.get("question", "")
        price = self._parse_price(market)
        volume = float(market.get("volume", 0))
        end_date = market.get("endDate", "unknown")

        news_context = "\n".join([
            f"- [{a.get('sentiment_label', '?')} ({a.get('sentiment_vader', 0):+.2f})] {a['title']}"
            for a in news[:8]
        ]) if news else "No news found."

        lessons_ctx = f"\n## Lessons from Past Trades\n{lessons}" if lessons else ""

        prompt = f"""Quick analysis for prediction market. Be decisive.

Market: {question}
Current price: {price*100:.0f}% YES | End: {end_date} | Volume: ${volume:,.0f}

News:
{news_context}
{lessons_ctx}

Respond ONLY with JSON:
{{"probability": 0.XX, "confidence": 0.XX, "direction": "yes"/"no", "reasoning": "1 sentence", "key_factors": ["f1","f2"]}}"""

        return await self._call_claude(prompt)

    async def _web_research(self, question: str) -> str:
        """Fetch additional context from Google News about the market topic."""
        keywords = question.replace("?", "").replace("Will ", "").replace("will ", "")[:80]
        try:
            url = f"https://news.google.com/rss/search?q={keywords}&hl=en-US&gl=US&ceid=US:en"
            resp = await self._http.get(url)
            feed = feedparser.parse(resp.text)
            articles = []
            for entry in feed.entries[:5]:
                articles.append(f"- {entry.title}")
            return "Recent web search results:\n" + "\n".join(articles) if articles else "No additional web results found."
        except:
            return "Web search unavailable."

    async def _pass2_deep(self, market: dict, news: list[dict], web_context: str, pass1: dict, lessons: str) -> dict:
        """Pass 2: Deep analysis incorporating web research and Pass 1 findings."""
        question = market.get("question", "")
        price = self._parse_price(market)
        end_date = market.get("endDate", "unknown")

        news_context = "\n".join([
            f"- [{a.get('sentiment_label', '?')}] {a['title']}"
            for a in news[:6]
        ]) if news else "No news."

        lessons_ctx = f"\n## Historical Lessons\n{lessons}" if lessons else ""

        prompt = f"""Deep analysis for prediction market. You have additional web research data.

Market: {question}
Current price: {price*100:.0f}% YES | End: {end_date}

Initial assessment (Pass 1): {pass1['probability']*100:.0f}% probability, reasoning: {pass1.get('reasoning', '')}

News headlines:
{news_context}

{web_context}
{lessons_ctx}

Consider:
1. Base rates - how often do events like this happen historically?
2. Web research findings - do they support or contradict the initial assessment?
3. Time until resolution - is there time for things to change?
4. Market efficiency - is the market likely correct?

Respond ONLY with JSON:
{{"probability": 0.XX, "confidence": 0.XX, "direction": "yes"/"no", "reasoning": "2-3 sentences", "key_factors": ["f1","f2","f3"]}}"""

        return await self._call_claude(prompt)

    async def _pass3_devils_advocate(self, market: dict, pass2: dict) -> dict:
        """Pass 3: Challenge the thesis. What could go wrong?"""
        question = market.get("question", "")
        price = self._parse_price(market)

        prompt = f"""You are a devil's advocate challenging a prediction market thesis.

Market: {question}
Current market price: {price*100:.0f}%
Our estimate: {pass2['probability']*100:.0f}% (direction: {pass2['direction']})
Our reasoning: {pass2.get('reasoning', '')}

Your job:
1. Find the STRONGEST argument AGAINST our position
2. Identify risks we might be overlooking
3. After considering the counter-arguments, give your FINAL adjusted probability

Be brutally honest. If our analysis has a blind spot, call it out.

Respond ONLY with JSON:
{{
    "counter_argument": "strongest argument against our position",
    "risks": ["risk1", "risk2"],
    "probability": 0.XX,
    "confidence": 0.XX,
    "direction": "yes"/"no",
    "reasoning": "final verdict after considering all angles",
    "final_verdict": "STRONG_BUY" or "BUY" or "HOLD" or "SKIP"
}}"""

        return await self._call_claude(prompt)

    async def _call_claude(self, prompt: str) -> dict:
        """Call Claude and parse JSON response."""
        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)
            result["probability"] = max(0.01, min(0.99, float(result.get("probability", 0.5))))
            result["confidence"] = max(0.1, min(1.0, float(result.get("confidence", 0.5))))
            if result.get("direction") not in ("yes", "no"):
                result["direction"] = "yes" if result["probability"] > 0.5 else "no"
            return result
        except Exception as e:
            print(f"[DeepAnalyst] Claude error: {e}")
            return {"probability": 0.5, "confidence": 0.1, "direction": "yes", "reasoning": f"Error: {e}"}

    @staticmethod
    def _parse_price(market: dict) -> float:
        prices = market.get("outcomePrices", "[0.5,0.5]")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except:
                prices = [0.5, 0.5]
        return float(prices[0]) if prices else 0.5

    async def close(self):
        await self._http.aclose()
