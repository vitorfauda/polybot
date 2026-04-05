"""Analysis routes - news collection and market scoring."""

from fastapi import APIRouter, Query
from services.polymarket.client import PolymarketClient
from services.news.pipeline import NewsPipeline
from services.analysis.scorer import OpportunityScorer
from services.risk.kelly import KellySizer

router = APIRouter()


@router.get("/news")
async def get_latest_news(
    category: str = Query(None),
    limit: int = Query(20, ge=1, le=50),
):
    """Get latest news with sentiment analysis."""
    pipeline = NewsPipeline()
    try:
        categories = [category] if category else None
        articles = await pipeline.collect_all(categories=categories)
        return {"news": articles[:limit], "count": len(articles)}
    finally:
        await pipeline.close()


@router.get("/news/market/{condition_id}")
async def get_news_for_market(condition_id: str):
    """Get news specifically related to a market."""
    poly_client = PolymarketClient()
    pipeline = NewsPipeline()
    try:
        market = await poly_client.get_market(condition_id)
        question = market.get("question", "")
        articles = await pipeline.collect_for_market(question)
        return {
            "market": question,
            "news": articles,
            "count": len(articles),
        }
    finally:
        await poly_client.close()
        await pipeline.close()


@router.get("/scan")
async def scan_opportunities(
    category: str = Query(None),
    min_edge: float = Query(0.05, ge=0.01, le=0.5),
    limit: int = Query(10, ge=1, le=50),
    bankroll: float = Query(1000, ge=10),
):
    """Scan markets and return ranked opportunities with position sizing."""
    poly_client = PolymarketClient()
    pipeline = NewsPipeline()
    scorer = OpportunityScorer()
    sizer = KellySizer()

    try:
        # Fetch active markets
        markets = await poly_client.get_active_markets(limit=50, category=category)

        # Score each market
        scores = []
        for market in markets:
            question = market.get("question", "")
            if not question:
                continue

            # Get related news
            articles = await pipeline.collect_for_market(question, max_results=5)

            # Score opportunity
            score = scorer.score_opportunity(market, articles)
            scores.append(score)

        # Rank by score
        ranked = scorer.rank_opportunities(scores, min_edge=min_edge)

        # Add position sizing
        results = []
        for s in ranked[:limit]:
            sizing = sizer.calculate(
                estimated_prob=s.estimated_probability,
                market_price=s.current_price,
                bankroll=bankroll,
                direction=s.direction,
            )
            results.append({
                "market_id": s.market_id,
                "question": s.question,
                "category": s.category,
                "current_price": s.current_price,
                "estimated_probability": s.estimated_probability,
                "edge": round(s.edge, 4),
                "confidence": s.confidence,
                "direction": s.direction,
                "news_sentiment": s.news_sentiment,
                "news_count": s.news_count,
                "score": s.score,
                "sizing": {
                    "kelly_full": sizing.kelly_full,
                    "kelly_fraction": sizing.kelly_fraction,
                    "bet_size_usd": sizing.bet_size_usd,
                    "expected_value": sizing.expected_value,
                    "risk_reward": sizing.risk_reward_ratio,
                },
            })

        return {"opportunities": results, "total_scanned": len(markets)}
    finally:
        await poly_client.close()
        await pipeline.close()


@router.get("/kelly")
async def calculate_kelly(
    estimated_prob: float = Query(..., ge=0.01, le=0.99),
    market_price: float = Query(..., ge=0.01, le=0.99),
    bankroll: float = Query(1000, ge=10),
    direction: str = Query("yes"),
):
    """Calculate Kelly position sizing for a specific opportunity."""
    sizer = KellySizer()
    result = sizer.calculate(estimated_prob, market_price, bankroll, direction)
    return {
        "kelly_full_pct": f"{result.kelly_full * 100:.1f}%",
        "kelly_fraction_pct": f"{result.kelly_fraction * 100:.1f}%",
        "bet_size_usd": result.bet_size_usd,
        "expected_value": result.expected_value,
        "risk_reward_ratio": result.risk_reward_ratio,
    }
