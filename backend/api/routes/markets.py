"""Markets routes - fetch and browse Polymarket markets."""

from fastapi import APIRouter, Query
from typing import Optional
from services.polymarket.client import PolymarketClient

router = APIRouter()


@router.get("/")
async def list_markets(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    category: Optional[str] = None,
):
    """List active markets from Polymarket."""
    client = PolymarketClient()
    try:
        markets = await client.get_active_markets(
            limit=limit, offset=offset, category=category
        )
        # Normalize response
        results = []
        for m in markets:
            prices = m.get("outcomePrices", "[]")
            if isinstance(prices, str):
                import json
                try:
                    prices = json.loads(prices)
                except:
                    prices = [0.5, 0.5]

            tokens = m.get("clobTokenIds", "[]")
            if isinstance(tokens, str):
                try:
                    tokens = json.loads(tokens)
                except:
                    tokens = []

            results.append({
                "id": m.get("conditionId", m.get("id")),
                "question": m.get("question", ""),
                "category": m.get("groupItemTitle", ""),
                "end_date": m.get("endDate"),
                "volume": float(m.get("volume", 0)),
                "liquidity": float(m.get("liquidity", 0)),
                "price_yes": float(prices[0]) if len(prices) > 0 else 0.5,
                "price_no": float(prices[1]) if len(prices) > 1 else 0.5,
                "token_id_yes": tokens[0] if len(tokens) > 0 else "",
                "token_id_no": tokens[1] if len(tokens) > 1 else "",
                "image": m.get("image"),
                "icon": m.get("icon"),
            })
        return {"markets": results, "count": len(results)}
    finally:
        await client.close()


@router.get("/search")
async def search_markets(q: str = Query(..., min_length=2)):
    """Search markets by keyword."""
    client = PolymarketClient()
    try:
        results = await client.search_markets(q)
        return {"markets": results, "count": len(results)}
    finally:
        await client.close()


@router.get("/categories")
async def list_categories():
    """List available market categories."""
    client = PolymarketClient()
    try:
        tags = await client.get_categories()
        return {"categories": tags}
    finally:
        await client.close()


@router.get("/{condition_id}")
async def get_market(condition_id: str):
    """Get details for a specific market."""
    client = PolymarketClient()
    try:
        market = await client.get_market(condition_id)
        return market
    finally:
        await client.close()


@router.get("/{condition_id}/history")
async def get_price_history(
    condition_id: str,
    token_id: str = Query(...),
    interval: str = Query("1d"),
):
    """Get price history for a market token."""
    client = PolymarketClient()
    try:
        history = await client.get_price_history(token_id, interval=interval)
        return {"history": history}
    finally:
        await client.close()


@router.get("/{condition_id}/orderbook")
async def get_orderbook(condition_id: str, token_id: str = Query(...)):
    """Get order book for a market token."""
    client = PolymarketClient()
    try:
        book = await client.get_orderbook(token_id)
        return book
    finally:
        await client.close()
