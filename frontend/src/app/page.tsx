"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import {
  TrendingUp,
  TrendingDown,
  Newspaper,
  Target,
  DollarSign,
  BarChart3,
  Activity,
  RefreshCw,
  Zap,
  AlertTriangle,
  Play,
  CheckCircle,
  XCircle,
  Brain,
  Wallet,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Market {
  id: string;
  question: string;
  category: string;
  volume: number;
  liquidity: number;
  price_yes: number;
  price_no: number;
  image?: string;
}

interface NewsArticle {
  source: string;
  title: string;
  url: string;
  published_at: string;
  sentiment_vader: number;
  sentiment_label: string;
}

interface Opportunity {
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

interface Portfolio {
  mode: string;
  balance: number;
  invested: number;
  total_value: number;
  total_pnl: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  open_positions: number;
  total_trades: number;
}

interface TradeRecord {
  trade_id: string;
  market_id: string;
  question: string;
  side: string;
  direction: string;
  price: number;
  size: number;
  cost: number;
  mode: string;
  status: string;
  timestamp: string;
  edge: number;
  kelly_fraction: number;
}

interface Position {
  trade_id: string;
  market_id: string;
  question: string;
  direction: string;
  shares: number;
  entry_price: number;
  cost: number;
  timestamp: string;
  status: string;
  pnl?: number;
  outcome?: string;
}

interface DashboardData {
  top_markets: Market[];
  latest_news: NewsArticle[];
  stats: {
    markets_tracked: number;
    news_collected: number;
    avg_sentiment: number;
    sentiment_label: string;
  };
  portfolio: Portfolio;
}

function formatUSD(n: number) {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
}

function SentimentBadge({ score }: { score: number }) {
  if (score > 0.05)
    return <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">Positive {score.toFixed(2)}</Badge>;
  if (score < -0.05)
    return <Badge className="bg-red-500/20 text-red-400 border-red-500/30">Negative {score.toFixed(2)}</Badge>;
  return <Badge className="bg-zinc-500/20 text-zinc-400 border-zinc-500/30">Neutral {score.toFixed(2)}</Badge>;
}

function EdgeBadge({ edge }: { edge: number }) {
  const pct = (edge * 100).toFixed(1);
  if (edge > 0.1)
    return <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30">+{pct}% edge</Badge>;
  if (edge > 0.05)
    return <Badge className="bg-yellow-500/20 text-yellow-400 border-yellow-500/30">+{pct}% edge</Badge>;
  return <Badge className="bg-zinc-500/20 text-zinc-400 border-zinc-500/30">+{pct}% edge</Badge>;
}

export default function Dashboard() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [oppLoading, setOppLoading] = useState(false);
  const [autoTrading, setAutoTrading] = useState(false);
  const [autoTradeResult, setAutoTradeResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchDashboard = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/dashboard/overview`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setDashboard(data);
      setLastUpdate(new Date());
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to connect to API");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchOpportunities = useCallback(async () => {
    try {
      setOppLoading(true);
      const res = await fetch(`${API_BASE}/api/analysis/scan?bankroll=1000&min_edge=0.03`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setOpportunities(data.opportunities || []);
    } catch {
      // silent
    } finally {
      setOppLoading(false);
    }
  }, []);

  const fetchTrades = useCallback(async () => {
    try {
      const [posRes, tradeRes] = await Promise.all([
        fetch(`${API_BASE}/api/trades/positions`),
        fetch(`${API_BASE}/api/trades/history`),
      ]);
      if (posRes.ok) {
        const posData = await posRes.json();
        setPositions(posData.positions || []);
      }
      if (tradeRes.ok) {
        const tradeData = await tradeRes.json();
        setTrades(tradeData.trades || []);
      }
    } catch {
      // silent
    }
  }, []);

  const runAutoScan = useCallback(async () => {
    try {
      setAutoTrading(true);
      setAutoTradeResult(null);
      const res = await fetch(
        `${API_BASE}/api/trades/auto-scan?bankroll=1000&min_edge=0.05&min_score=0.3&max_trades=3&use_llm=true`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setAutoTradeResult(
        `Scanned ${data.scanned} markets, found ${data.opportunities_found} opportunities, executed ${data.trades_executed} trades`
      );
      // Refresh data
      await Promise.all([fetchDashboard(), fetchTrades()]);
    } catch (e: unknown) {
      setAutoTradeResult(`Error: ${e instanceof Error ? e.message : "unknown"}`);
    } finally {
      setAutoTrading(false);
    }
  }, [fetchDashboard, fetchTrades]);

  const resolvePosition = useCallback(async (tradeId: string, outcome: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/trades/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trade_id: tradeId, outcome }),
      });
      if (res.ok) {
        await Promise.all([fetchDashboard(), fetchTrades()]);
      }
    } catch {
      // silent
    }
  }, [fetchDashboard, fetchTrades]);

  useEffect(() => {
    fetchDashboard();
    fetchTrades();
  }, [fetchDashboard, fetchTrades]);

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-4">
          <Activity className="w-12 h-12 animate-pulse text-primary mx-auto" />
          <p className="text-muted-foreground">Loading PolyBot Dashboard...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-4">
        <Card className="max-w-md w-full">
          <CardContent className="pt-6 text-center space-y-4">
            <AlertTriangle className="w-12 h-12 text-yellow-500 mx-auto" />
            <h2 className="text-xl font-bold">Backend Not Connected</h2>
            <p className="text-muted-foreground text-sm">Start the backend server:</p>
            <pre className="bg-muted p-3 rounded text-xs text-left overflow-x-auto">
{`cd backend
source venv/Scripts/activate
uvicorn api.main:app --reload`}
            </pre>
            <button onClick={fetchDashboard} className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm hover:opacity-90">
              Retry Connection
            </button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const d = dashboard!;
  const portfolio = d.portfolio;
  const openPositions = positions.filter(p => p.status === "open");
  const closedPositions = positions.filter(p => p.status === "closed");

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className="w-8 h-8 text-yellow-500" />
            <div>
              <h1 className="text-2xl font-bold tracking-tight">PolyBot</h1>
              <p className="text-xs text-muted-foreground">AI Prediction Market Analyst</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <Badge variant="secondary" className="text-xs">
              <Wallet className="w-3 h-3 mr-1" />
              {portfolio.mode?.toUpperCase() || "SIMULATION"}
            </Badge>
            {lastUpdate && (
              <span className="text-xs text-muted-foreground">
                Updated {lastUpdate.toLocaleTimeString()}
              </span>
            )}
            <button onClick={() => { fetchDashboard(); fetchTrades(); }} className="p-2 hover:bg-muted rounded-md transition">
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <Card>
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
                <Wallet className="w-3.5 h-3.5" />
                Balance
              </div>
              <p className="text-2xl font-bold">{formatUSD(portfolio.balance || 0)}</p>
              <p className="text-xs text-muted-foreground">Invested: {formatUSD(portfolio.invested || 0)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
                <DollarSign className="w-3.5 h-3.5" />
                P&L
              </div>
              <p className={`text-2xl font-bold ${(portfolio.total_pnl || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {(portfolio.total_pnl || 0) >= 0 ? "+" : ""}{formatUSD(portfolio.total_pnl || 0)}
              </p>
              <p className="text-xs text-muted-foreground">
                Win rate: {portfolio.win_rate || 0}%
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
                <Target className="w-3.5 h-3.5" />
                Trades
              </div>
              <p className="text-2xl font-bold">{portfolio.total_trades || 0}</p>
              <p className="text-xs text-muted-foreground">
                {portfolio.win_count || 0}W / {portfolio.loss_count || 0}L
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
                <Newspaper className="w-3.5 h-3.5" />
                News
              </div>
              <p className="text-2xl font-bold">{d.stats.news_collected}</p>
              <SentimentBadge score={d.stats.avg_sentiment} />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
                <BarChart3 className="w-3.5 h-3.5" />
                Markets
              </div>
              <p className="text-2xl font-bold">{d.stats.markets_tracked}</p>
              <p className="text-xs text-muted-foreground">Active tracked</p>
            </CardContent>
          </Card>
        </div>

        {/* Auto-Trade Button */}
        <Card className="border-yellow-500/30">
          <CardContent className="py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Brain className="w-6 h-6 text-yellow-500" />
                <div>
                  <h3 className="font-medium text-sm">AI Auto-Scanner</h3>
                  <p className="text-xs text-muted-foreground">
                    Scan markets, analyze with Claude AI, and execute best opportunities (simulation mode)
                  </p>
                </div>
              </div>
              <button
                onClick={runAutoScan}
                disabled={autoTrading}
                className="px-4 py-2 bg-yellow-500 text-black rounded-md text-sm font-medium hover:bg-yellow-400 disabled:opacity-50 flex items-center gap-2"
              >
                {autoTrading ? (
                  <>
                    <Activity className="w-4 h-4 animate-spin" />
                    Scanning...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4" />
                    Run Auto-Scan
                  </>
                )}
              </button>
            </div>
            {autoTradeResult && (
              <p className="text-xs text-muted-foreground mt-2 bg-muted p-2 rounded">
                {autoTradeResult}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Main Content Tabs */}
        <Tabs defaultValue="positions" className="space-y-4">
          <TabsList>
            <TabsTrigger value="positions">
              Positions ({openPositions.length})
            </TabsTrigger>
            <TabsTrigger value="markets">Top Markets</TabsTrigger>
            <TabsTrigger value="opportunities" onClick={fetchOpportunities}>
              Opportunities
            </TabsTrigger>
            <TabsTrigger value="history">Trade History</TabsTrigger>
            <TabsTrigger value="news">News Feed</TabsTrigger>
          </TabsList>

          {/* Positions Tab */}
          <TabsContent value="positions" className="space-y-3">
            {openPositions.length === 0 && closedPositions.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center">
                  <Target className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">
                    No positions yet. Use the Auto-Scanner to find and execute trades.
                  </p>
                </CardContent>
              </Card>
            ) : (
              <>
                {openPositions.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-medium text-muted-foreground">Open Positions</h3>
                    {openPositions.map((pos) => (
                      <Card key={pos.trade_id} className="border-yellow-500/20">
                        <CardContent className="py-3">
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1 min-w-0">
                              <h4 className="font-medium text-sm leading-tight mb-1">{pos.question}</h4>
                              <div className="flex items-center gap-2 text-xs">
                                <Badge className={pos.direction === "yes" ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}>
                                  {pos.direction.toUpperCase()}
                                </Badge>
                                <span className="text-muted-foreground">
                                  {pos.shares.toFixed(1)} shares @ {formatUSD(pos.entry_price)}
                                </span>
                                <span className="text-muted-foreground">
                                  Cost: {formatUSD(pos.cost)}
                                </span>
                              </div>
                            </div>
                            <div className="flex gap-2 shrink-0">
                              <button
                                onClick={() => resolvePosition(pos.trade_id, "yes")}
                                className="px-3 py-1 bg-emerald-500/20 text-emerald-400 rounded text-xs hover:bg-emerald-500/30 flex items-center gap-1"
                              >
                                <CheckCircle className="w-3 h-3" /> YES Won
                              </button>
                              <button
                                onClick={() => resolvePosition(pos.trade_id, "no")}
                                className="px-3 py-1 bg-red-500/20 text-red-400 rounded text-xs hover:bg-red-500/30 flex items-center gap-1"
                              >
                                <XCircle className="w-3 h-3" /> NO Won
                              </button>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}
                {closedPositions.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-medium text-muted-foreground mt-4">Closed Positions</h3>
                    {closedPositions.map((pos) => (
                      <Card key={pos.trade_id} className="opacity-70">
                        <CardContent className="py-3">
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1 min-w-0">
                              <h4 className="font-medium text-sm leading-tight mb-1">{pos.question}</h4>
                              <div className="flex items-center gap-2 text-xs">
                                <Badge className={pos.direction === "yes" ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}>
                                  {pos.direction.toUpperCase()}
                                </Badge>
                                <span className="text-muted-foreground">
                                  Outcome: {pos.outcome?.toUpperCase()}
                                </span>
                              </div>
                            </div>
                            <div className="text-right">
                              <span className={`text-sm font-bold ${(pos.pnl || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                {(pos.pnl || 0) >= 0 ? "+" : ""}{formatUSD(pos.pnl || 0)}
                              </span>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}
              </>
            )}
          </TabsContent>

          {/* Markets Tab */}
          <TabsContent value="markets" className="space-y-3">
            {d.top_markets.map((market) => (
              <Card key={market.id} className="hover:bg-muted/30 transition">
                <CardContent className="py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-sm leading-tight mb-2">{market.question}</h3>
                      <div className="flex items-center gap-2 flex-wrap">
                        {market.category && <Badge variant="secondary" className="text-xs">{market.category}</Badge>}
                        <span className="text-xs text-muted-foreground">Vol: {formatUSD(market.volume)}</span>
                        <span className="text-xs text-muted-foreground">Liq: {formatUSD(market.liquidity)}</span>
                      </div>
                    </div>
                    <div className="flex gap-3 shrink-0">
                      <div className="text-center">
                        <div className="text-xs text-muted-foreground mb-1">YES</div>
                        <div className="flex items-center gap-1">
                          <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                          <span className="font-mono font-bold text-emerald-400">{(market.price_yes * 100).toFixed(0)}%</span>
                        </div>
                      </div>
                      <Separator orientation="vertical" className="h-10" />
                      <div className="text-center">
                        <div className="text-xs text-muted-foreground mb-1">NO</div>
                        <div className="flex items-center gap-1">
                          <TrendingDown className="w-3.5 h-3.5 text-red-400" />
                          <span className="font-mono font-bold text-red-400">{(market.price_no * 100).toFixed(0)}%</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </TabsContent>

          {/* Opportunities Tab */}
          <TabsContent value="opportunities" className="space-y-3">
            {oppLoading ? (
              <Card>
                <CardContent className="py-8 text-center">
                  <Activity className="w-8 h-8 animate-pulse text-primary mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">Scanning markets & analyzing news...</p>
                </CardContent>
              </Card>
            ) : opportunities.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center">
                  <Target className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">Click the tab to scan for opportunities</p>
                </CardContent>
              </Card>
            ) : (
              opportunities.map((opp, i) => (
                <Card key={opp.market_id} className="hover:bg-muted/30 transition">
                  <CardContent className="py-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-mono text-muted-foreground">#{i + 1}</span>
                          <Badge className={opp.score > 0.5 ? "bg-emerald-500/20 text-emerald-400" : opp.score > 0.3 ? "bg-yellow-500/20 text-yellow-400" : "bg-zinc-500/20 text-zinc-400"}>
                            Score: {(opp.score * 100).toFixed(0)}
                          </Badge>
                          <EdgeBadge edge={opp.edge} />
                        </div>
                        <h3 className="font-medium text-sm leading-tight mb-2">{opp.question}</h3>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                          <div>
                            <span className="text-muted-foreground">Direction: </span>
                            <span className={opp.direction === "yes" ? "text-emerald-400 font-bold" : "text-red-400 font-bold"}>
                              {opp.direction.toUpperCase()}
                            </span>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Price: </span>
                            <span className="font-mono">{(opp.current_price * 100).toFixed(0)}%</span>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Est. Prob: </span>
                            <span className="font-mono">{(opp.estimated_probability * 100).toFixed(0)}%</span>
                          </div>
                          <div>
                            <span className="text-muted-foreground">News: </span>
                            <span>{opp.news_count} articles</span>
                          </div>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-xs text-muted-foreground mb-1">Suggested Bet</div>
                        <div className="text-lg font-bold text-primary">{formatUSD(opp.sizing.bet_size_usd)}</div>
                        <div className="text-xs text-muted-foreground">EV: {formatUSD(opp.sizing.expected_value)}</div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </TabsContent>

          {/* Trade History Tab */}
          <TabsContent value="history" className="space-y-3">
            {trades.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center">
                  <BarChart3 className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">No trades yet</p>
                </CardContent>
              </Card>
            ) : (
              trades.slice().reverse().map((trade) => (
                <Card key={trade.trade_id} className="hover:bg-muted/30 transition">
                  <CardContent className="py-3">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge variant="secondary" className="text-xs font-mono">{trade.trade_id}</Badge>
                          <Badge className={trade.status === "filled" ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}>
                            {trade.status}
                          </Badge>
                        </div>
                        <h4 className="font-medium text-sm leading-tight mb-1">{trade.question}</h4>
                        <div className="flex items-center gap-3 text-xs text-muted-foreground">
                          <span>{trade.direction.toUpperCase()}</span>
                          <span>{trade.size.toFixed(1)} shares</span>
                          <span>@ {formatUSD(trade.price)}</span>
                          <span>Edge: {(trade.edge * 100).toFixed(1)}%</span>
                          <span>{new Date(trade.timestamp).toLocaleString()}</span>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="font-bold">{formatUSD(trade.cost)}</div>
                        <div className="text-xs text-muted-foreground">{trade.mode}</div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </TabsContent>

          {/* News Tab */}
          <TabsContent value="news" className="space-y-3">
            {d.latest_news.map((news, i) => (
              <Card key={i} className="hover:bg-muted/30 transition">
                <CardContent className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <a href={news.url} target="_blank" rel="noopener noreferrer" className="font-medium text-sm hover:underline leading-tight block mb-1">
                        {news.title}
                      </a>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span>{news.source}</span>
                        {news.published_at && <span>{new Date(news.published_at).toLocaleDateString()}</span>}
                      </div>
                    </div>
                    <SentimentBadge score={news.sentiment_vader} />
                  </div>
                </CardContent>
              </Card>
            ))}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
