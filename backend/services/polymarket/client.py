"""Polymarket API client wrapper for market discovery and data."""

import httpx
from datetime import datetime
from typing import Optional
from core.config import get_settings


class PolymarketClient:
    """Wrapper around Polymarket's Gamma and CLOB APIs for market data."""

    def __init__(self):
        self.settings = get_settings()
        self.gamma_url = self.settings.gamma_api_url
        self.clob_url = self.settings.polymarket_host
        self.data_url = self.settings.data_api_url
        self._http = httpx.AsyncClient(timeout=30.0)

    async def get_active_markets(
        self,
        limit: int = 50,
        offset: int = 0,
        category: Optional[str] = None,
        order: str = "volume",
    ) -> list[dict]:
        """Fetch active markets from Gamma API."""
        params = {
            "limit": limit,
            "offset": offset,
            "active": "true",
            "closed": "false",
            "order": order,
            "ascending": "false",
        }
        if category:
            params["tag"] = category

        resp = await self._http.get(f"{self.gamma_url}/markets", params=params)
        resp.raise_for_status()
        return resp.json()

    async def search_markets(self, query: str, limit: int = 20) -> list[dict]:
        """Search markets by keyword."""
        params = {"query": query, "limit": limit}
        resp = await self._http.get(f"{self.gamma_url}/public-search", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_market(self, condition_id: str) -> dict:
        """Get single market details."""
        resp = await self._http.get(f"{self.gamma_url}/markets/{condition_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_events(self, limit: int = 20) -> list[dict]:
        """Get events (groups of related markets)."""
        params = {"limit": limit, "active": "true", "closed": "false"}
        resp = await self._http.get(f"{self.gamma_url}/events", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_orderbook(self, token_id: str) -> dict:
        """Get order book for a token."""
        params = {"token_id": token_id}
        resp = await self._http.get(f"{self.clob_url}/book", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_midpoint(self, token_id: str) -> float:
        """Get midpoint price for a token."""
        params = {"token_id": token_id}
        resp = await self._http.get(f"{self.clob_url}/midpoint", params=params)
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("mid", 0))

    async def get_price(self, token_id: str, side: str = "buy") -> float:
        """Get best price for a token (buy or sell side)."""
        params = {"token_id": token_id, "side": side.upper()}
        resp = await self._http.get(f"{self.clob_url}/price", params=params)
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("price", 0))

    async def get_price_history(
        self,
        token_id: str,
        interval: str = "1d",
        fidelity: int = 60,
    ) -> list[dict]:
        """Get historical prices. interval: 1h, 6h, 1d, 1w, 1m, max, all."""
        params = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        }
        resp = await self._http.get(f"{self.clob_url}/prices-history", params=params)
        resp.raise_for_status()
        return resp.json().get("history", [])

    async def get_spread(self, token_id: str) -> dict:
        """Get bid-ask spread."""
        params = {"token_id": token_id}
        resp = await self._http.get(f"{self.clob_url}/spread", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_market_trades(
        self, condition_id: str, limit: int = 50
    ) -> list[dict]:
        """Get recent trades for a market from Data API."""
        params = {"market": condition_id, "limit": limit}
        resp = await self._http.get(f"{self.data_url}/trades", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_categories(self) -> list[str]:
        """Get available market categories/tags."""
        resp = await self._http.get(f"{self.gamma_url}/tags")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._http.aclose()
