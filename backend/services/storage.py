"""Supabase storage service for persisting trades, portfolio, news, and analyses."""

from datetime import datetime, timezone
from supabase import create_client
from core.config import get_settings


class StorageService:
    """Persists all PolyBot data to Supabase PostgreSQL."""

    def __init__(self):
        settings = get_settings()
        # Extract URL and key from DATABASE_URL or use direct config
        self.supabase_url = settings.supabase_url
        self.supabase_key = settings.supabase_key
        if self.supabase_url and self.supabase_key:
            self.client = create_client(self.supabase_url, self.supabase_key)
        else:
            self.client = None

    def _check(self):
        if not self.client:
            raise RuntimeError("Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY in .env")

    # ── Portfolio ──

    def get_portfolio(self, profile: str | None = None) -> dict:
        """Get portfolio for a specific profile, or default if not specified."""
        self._check()
        if profile:
            try:
                res = self.client.table("portfolio").select("*").eq("profile", profile).limit(1).execute()
                if res.data:
                    return res.data[0]
            except:
                pass
        res = self.client.table("portfolio").select("*").order("id", desc=True).limit(1).execute()
        if res.data:
            return res.data[0]
        return {"total_balance": 1000, "invested": 0, "available": 1000, "total_pnl": 0, "win_count": 0, "loss_count": 0}

    def get_all_portfolios(self) -> list[dict]:
        """Get all profile portfolios."""
        self._check()
        try:
            res = self.client.table("portfolio").select("*").execute()
            return res.data or []
        except:
            return []

    def update_portfolio(self, updates: dict, profile: str | None = None) -> dict:
        self._check()
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        portfolio = self.get_portfolio(profile=profile)
        self.client.table("portfolio").update(updates).eq("id", portfolio["id"]).execute()
        return self.get_portfolio(profile=profile)

    # ── Trades ──

    def save_trade(self, trade: dict) -> dict:
        self._check()
        row = {
            "market_id": trade.get("market_id", ""),
            "side": trade.get("side", "buy"),
            "direction": trade.get("direction", "yes"),
            "price": trade.get("price", 0),
            "size": trade.get("size", 0),
            "cost": trade.get("cost", 0),
            "order_type": trade.get("order_type", "limit"),
            "status": trade.get("status", "simulated"),
            "created_at": trade.get("timestamp", datetime.now(timezone.utc).isoformat()),
        }
        if trade.get("analysis_id"):
            row["analysis_id"] = trade["analysis_id"]

        # Try with extended columns, fallback to basic if schema not cached yet
        extended = {
            "question": trade.get("question", ""),
            "end_date": trade.get("end_date"),
            "edge": trade.get("edge", 0),
            "reasoning": trade.get("reasoning", ""),
        }
        if trade.get("profile"):
            extended["profile"] = trade["profile"]
        try:
            res = self.client.table("trades").insert({**row, **extended}).execute()
        except Exception:
            try:
                # Remove profile if it fails
                extended.pop("profile", None)
                res = self.client.table("trades").insert({**row, **extended}).execute()
            except Exception:
                res = self.client.table("trades").insert(row).execute()
        return res.data[0] if res.data else {**row, **extended}

    def get_trades(self, limit: int = 50, profile: str | None = None) -> list[dict]:
        self._check()
        q = self.client.table("trades").select("*").order("created_at", desc=True).limit(limit)
        if profile:
            try:
                q = q.eq("profile", profile)
            except:
                pass
        res = q.execute()
        return res.data or []

    def get_open_trades(self) -> list[dict]:
        self._check()
        res = self.client.table("trades").select("*").eq("status", "simulated").order("created_at", desc=True).execute()
        return res.data or []

    def resolve_trade(self, trade_id: int, outcome: str, pnl: float) -> dict | None:
        self._check()
        status = "won" if pnl > 0 else "lost"
        updates = {
            "status": status,
            "pnl": pnl,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        res = self.client.table("trades").update(updates).eq("id", trade_id).execute()
        return res.data[0] if res.data else None

    # ── Analyses ──

    def save_analysis(self, analysis: dict) -> dict:
        self._check()
        row = {
            "market_id": analysis.get("market_id", ""),
            "llm_analysis": analysis.get("reasoning", ""),
            "confidence_score": analysis.get("confidence", 0),
            "predicted_direction": analysis.get("direction", ""),
            "predicted_probability": analysis.get("probability", 0),
            "market_price": analysis.get("market_price", 0),
            "edge": analysis.get("edge", 0),
            "recommended_action": analysis.get("recommended_action", ""),
            "recommended_size": analysis.get("recommended_size", 0),
            "kelly_fraction": analysis.get("kelly_fraction", 0),
        }
        res = self.client.table("analyses").insert(row).execute()
        return res.data[0] if res.data else row

    def get_analyses(self, market_id: str = None, limit: int = 20) -> list[dict]:
        self._check()
        q = self.client.table("analyses").select("*").order("created_at", desc=True).limit(limit)
        if market_id:
            q = q.eq("market_id", market_id)
        return q.execute().data or []

    # ── News ──

    def save_news(self, articles: list[dict]) -> int:
        self._check()
        rows = []
        for a in articles:
            rows.append({
                "source": a.get("source", ""),
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "content_summary": a.get("content_summary", ""),
                "published_at": a["published_at"].isoformat() if a.get("published_at") else None,
                "sentiment_vader": a.get("sentiment_vader", 0),
                "sentiment_label": a.get("sentiment_label", "neutral"),
            })
        if rows:
            self.client.table("news").insert(rows).execute()
        return len(rows)

    def get_recent_news(self, limit: int = 30) -> list[dict]:
        self._check()
        res = self.client.table("news").select("*").order("published_at", desc=True).limit(limit).execute()
        return res.data or []

    # ── Markets ──

    def save_markets(self, markets: list[dict]) -> int:
        self._check()
        import json
        rows = []
        for m in markets:
            prices = m.get("outcomePrices", "[0.5,0.5]")
            if isinstance(prices, str):
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

            rows.append({
                "id": m.get("conditionId", m.get("id", "")),
                "condition_id": m.get("conditionId", ""),
                "token_id_yes": tokens[0] if len(tokens) > 0 else "",
                "token_id_no": tokens[1] if len(tokens) > 1 else "",
                "question": m.get("question", ""),
                "category": m.get("groupItemTitle", ""),
                "end_date": m.get("endDate"),
                "volume": float(m.get("volume", 0)),
                "liquidity": float(m.get("liquidity", 0)),
                "current_price_yes": float(prices[0]) if prices else 0.5,
                "current_price_no": float(prices[1]) if len(prices) > 1 else 0.5,
                "status": "active",
            })
        if rows:
            self.client.table("markets").upsert(rows, on_conflict="id").execute()
        return len(rows)

    # ── Stats ──

    def get_stats(self) -> dict:
        self._check()
        portfolio = self.get_portfolio()
        trades = self.client.table("trades").select("id", count="exact").execute()
        wins = self.client.table("trades").select("id", count="exact").eq("status", "won").execute()
        losses = self.client.table("trades").select("id", count="exact").eq("status", "lost").execute()
        total = trades.count or 0
        w = wins.count or 0
        l = losses.count or 0
        return {
            "total_balance": portfolio.get("total_balance", 0),
            "invested": portfolio.get("invested", 0),
            "total_pnl": portfolio.get("total_pnl", 0),
            "total_trades": total,
            "win_count": w,
            "loss_count": l,
            "win_rate": round(w / (w + l) * 100, 1) if (w + l) > 0 else 0,
        }
