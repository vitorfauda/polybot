"""Market opportunity scorer - combines signals to rank opportunities."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketScore:
    market_id: str
    question: str
    category: str
    current_price: float
    estimated_probability: float
    edge: float  # estimated_prob - market_price (or vice versa for NO)
    confidence: float  # 0-1
    direction: str  # "yes" or "no"
    news_sentiment: float  # -1 to 1
    news_count: int
    volume_24h: float
    liquidity: float
    score: float  # final composite score
    reasoning: Optional[str] = None


class OpportunityScorer:
    """Scores and ranks market opportunities based on multiple signals."""

    # Weights for composite score
    WEIGHTS = {
        "edge": 0.35,
        "confidence": 0.25,
        "sentiment_alignment": 0.15,
        "liquidity": 0.10,
        "volume": 0.10,
        "news_freshness": 0.05,
    }

    def score_opportunity(
        self,
        market: dict,
        news_articles: list[dict],
        llm_probability: Optional[float] = None,
        llm_confidence: Optional[float] = None,
        llm_reasoning: Optional[str] = None,
    ) -> MarketScore:
        """Score a single market opportunity."""
        prices_raw = market.get("outcomePrices", "[0.5,0.5]")
        if isinstance(prices_raw, str):
            import json
            try:
                prices_list = json.loads(prices_raw)
            except:
                prices_list = [0.5, 0.5]
        else:
            prices_list = prices_raw
        current_price = float(prices_list[0]) if prices_list else 0.5
        volume = float(market.get("volume", 0))
        liquidity = float(market.get("liquidity", 0))

        # News sentiment analysis
        avg_sentiment = 0.0
        if news_articles:
            sentiments = [a.get("sentiment_vader", 0) for a in news_articles]
            avg_sentiment = sum(sentiments) / len(sentiments)

        # Estimate probability (use LLM if available, otherwise sentiment-adjusted)
        if llm_probability is not None:
            estimated_prob = llm_probability
            confidence = llm_confidence or 0.5
        else:
            # Simple sentiment-based adjustment (fallback)
            sentiment_adjustment = avg_sentiment * 0.1
            estimated_prob = max(0.01, min(0.99, current_price + sentiment_adjustment))
            confidence = 0.3  # low confidence without LLM

        # Calculate edge
        edge_yes = estimated_prob - current_price
        edge_no = (1 - estimated_prob) - (1 - current_price)

        if abs(edge_yes) >= abs(edge_no):
            direction = "yes"
            edge = edge_yes
        else:
            direction = "no"
            edge = edge_no

        # Sentiment alignment (does sentiment agree with our direction?)
        if direction == "yes":
            sentiment_alignment = max(0, avg_sentiment)
        else:
            sentiment_alignment = max(0, -avg_sentiment)

        # Normalize components to 0-1
        norm_edge = min(1.0, abs(edge) / 0.3)  # 30% edge = max score
        norm_confidence = confidence
        norm_sentiment = sentiment_alignment
        norm_liquidity = min(1.0, liquidity / 100000)  # $100k = max
        norm_volume = min(1.0, volume / 1000000)  # $1M = max
        norm_news = min(1.0, len(news_articles) / 10)

        # Composite score
        composite = (
            self.WEIGHTS["edge"] * norm_edge
            + self.WEIGHTS["confidence"] * norm_confidence
            + self.WEIGHTS["sentiment_alignment"] * norm_sentiment
            + self.WEIGHTS["liquidity"] * norm_liquidity
            + self.WEIGHTS["volume"] * norm_volume
            + self.WEIGHTS["news_freshness"] * norm_news
        )

        return MarketScore(
            market_id=market.get("conditionId", market.get("id", "")),
            question=market.get("question", ""),
            category=market.get("groupItemTitle", market.get("category", "other")),
            current_price=current_price,
            estimated_probability=estimated_prob,
            edge=edge,
            confidence=confidence,
            direction=direction,
            news_sentiment=avg_sentiment,
            news_count=len(news_articles),
            volume_24h=volume,
            liquidity=liquidity,
            score=round(composite, 4),
            reasoning=llm_reasoning,
        )

    def rank_opportunities(self, scores: list[MarketScore], min_edge: float = 0.05) -> list[MarketScore]:
        """Rank opportunities by score, filtering by minimum edge."""
        filtered = [s for s in scores if abs(s.edge) >= min_edge]
        return sorted(filtered, key=lambda s: s.score, reverse=True)
