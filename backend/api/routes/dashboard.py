"""Dashboard routes - aggregated stats for the frontend."""

from fastapi import APIRouter
from services.polymarket.client import PolymarketClient
from services.news.pipeline import NewsPipeline
from api.routes.trades import executor

router = APIRouter()


@router.get("/overview")
async def dashboard_overview():
    """Get dashboard overview data."""
    poly_client = PolymarketClient()
    pipeline = NewsPipeline()

    try:
        # Top markets by volume
        top_markets = await poly_client.get_active_markets(limit=10, order="volume")

        # Latest news
        news = await pipeline.collect_all()
        latest_news = sorted(
            [n for n in news if n.get("published_at")],
            key=lambda x: x["published_at"],
            reverse=True,
        )[:10]

        # Format markets
        formatted_markets = []
        for m in top_markets:
            prices = m.get("outcomePrices", "[]")
            if isinstance(prices, str):
                import json
                try:
                    prices = json.loads(prices)
                except:
                    prices = [0.5, 0.5]

            formatted_markets.append({
                "id": m.get("conditionId", m.get("id")),
                "question": m.get("question", ""),
                "category": m.get("groupItemTitle", ""),
                "volume": float(m.get("volume", 0)),
                "liquidity": float(m.get("liquidity", 0)),
                "price_yes": float(prices[0]) if prices else 0.5,
                "price_no": float(prices[1]) if len(prices) > 1 else 0.5,
                "image": m.get("image"),
            })

        # Sentiment summary
        sentiments = [n.get("sentiment_vader", 0) for n in news]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0

        return {
            "top_markets": formatted_markets,
            "latest_news": latest_news,
            "stats": {
                "markets_tracked": len(top_markets),
                "news_collected": len(news),
                "avg_sentiment": round(avg_sentiment, 3),
                "sentiment_label": "positive" if avg_sentiment > 0.05 else "negative" if avg_sentiment < -0.05 else "neutral",
            },
            "portfolio": executor.get_portfolio(),
        }
    finally:
        await poly_client.close()
        await pipeline.close()
