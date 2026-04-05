const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export interface Market {
  id: string;
  question: string;
  category: string;
  end_date: string;
  volume: number;
  liquidity: number;
  price_yes: number;
  price_no: number;
  token_id_yes: string;
  token_id_no: string;
  image?: string;
  icon?: string;
}

export interface NewsArticle {
  source: string;
  title: string;
  url: string;
  content_summary?: string;
  published_at: string;
  sentiment_vader: number;
  sentiment_label: string;
  category?: string;
}

export interface Opportunity {
  market_id: string;
  question: string;
  category: string;
  current_price: number;
  estimated_probability: number;
  edge: number;
  confidence: number;
  direction: string;
  news_sentiment: number;
  news_count: number;
  score: number;
  sizing: {
    kelly_full: number;
    kelly_fraction: number;
    bet_size_usd: number;
    expected_value: number;
    risk_reward: number;
  };
}

export interface DashboardData {
  top_markets: Market[];
  latest_news: NewsArticle[];
  stats: {
    markets_tracked: number;
    news_collected: number;
    avg_sentiment: number;
    sentiment_label: string;
  };
  portfolio: {
    total_balance: number;
    invested: number;
    available: number;
    total_pnl: number;
    win_rate: number;
    total_trades: number;
  };
}

export const api = {
  getDashboard: () => fetchAPI<DashboardData>("/api/dashboard/overview"),
  getMarkets: (limit = 20, category?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (category) params.set("category", category);
    return fetchAPI<{ markets: Market[]; count: number }>(`/api/markets/?${params}`);
  },
  searchMarkets: (q: string) =>
    fetchAPI<{ markets: Market[]; count: number }>(`/api/markets/search?q=${encodeURIComponent(q)}`),
  getNews: (category?: string) => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    return fetchAPI<{ news: NewsArticle[]; count: number }>(`/api/analysis/news?${params}`);
  },
  scanOpportunities: (bankroll = 1000, minEdge = 0.05) =>
    fetchAPI<{ opportunities: Opportunity[]; total_scanned: number }>(
      `/api/analysis/scan?bankroll=${bankroll}&min_edge=${minEdge}`
    ),
  getPriceHistory: (conditionId: string, tokenId: string, interval = "1d") =>
    fetchAPI<{ history: { t: number; p: number }[] }>(
      `/api/markets/${conditionId}/history?token_id=${tokenId}&interval=${interval}`
    ),
};
