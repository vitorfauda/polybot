"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Activity,
  Play,
  RefreshCw,
  Trophy,
  Target,
  Zap,
  TrendingUp,
  TrendingDown,
  Brain,
  Crosshair,
  Search,
  Shield,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ProfileTrade {
  id: number;
  question?: string;
  direction: string;
  price: number;
  cost: number;
  edge?: number;
  status: string;
  pnl?: number | null;
  reasoning?: string;
  end_date?: string;
  created_at: string;
}

interface ProfilePortfolio {
  total_balance?: number;
  invested?: number;
  available?: number;
  total_pnl?: number;
  win_count?: number;
  loss_count?: number;
}

interface ProfileData {
  name: string;
  display_name: string;
  description: string;
  settings: {
    min_edge: number;
    min_confidence: number;
    bet_size: number;
    max_hours: number;
    required_verdict: string[];
  };
  portfolio: ProfilePortfolio | null;
  stats: {
    total_trades: number;
    open: number;
    wins: number;
    losses: number;
    win_rate: number;
  };
  recent_trades: ProfileTrade[];
}

function formatUSD(n: number) {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(2)}K`;
  return `$${n.toFixed(2)}`;
}

function ProfileIcon({ name }: { name: string }) {
  if (name === "hunter") return <Crosshair className="w-6 h-6 text-red-400" />;
  if (name === "sniper") return <Target className="w-6 h-6 text-yellow-400" />;
  if (name === "scout") return <Search className="w-6 h-6 text-blue-400" />;
  return <Brain className="w-6 h-6" />;
}

function profileColor(name: string) {
  if (name === "hunter") return "border-red-500/30";
  if (name === "sniper") return "border-yellow-500/30";
  if (name === "scout") return "border-blue-500/30";
  return "";
}

export default function ProfilesPage() {
  const [profiles, setProfiles] = useState<ProfileData[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState<string | null>(null);
  const [scanResult, setScanResult] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);

  const fetchProfiles = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/trades/profiles`);
      const data = await res.json();
      setProfiles(data.profiles || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  const runScan = useCallback(async (profileName: string | "all") => {
    try {
      setScanning(profileName);
      setScanResult(null);
      const url = profileName === "all"
        ? `${API_BASE}/api/trades/scan-all-profiles`
        : `${API_BASE}/api/trades/scan-profile/${profileName}`;
      const res = await fetch(url, { method: "POST" });
      const data = await res.json();
      if (profileName === "all") {
        const summary = Object.entries(data).map(([name, r]: [string, unknown]) => {
          const result = r as { trades?: number; filtered?: number };
          return `${name}: ${result.trades || 0} trades from ${result.filtered || 0} filtered`;
        }).join(" | ");
        setScanResult(summary);
      } else {
        setScanResult(`${data.display_name}: ${data.trades || 0} trades from ${data.filtered || 0} filtered markets`);
      }
      await fetchProfiles();
    } catch (e) {
      setScanResult(`Error: ${e instanceof Error ? e.message : "unknown"}`);
    } finally {
      setScanning(null);
    }
  }, [fetchProfiles]);

  const resolveAll = useCallback(async () => {
    try {
      setResolving(true);
      const res = await fetch(`${API_BASE}/api/trades/resolve-all`, { method: "POST" });
      const data = await res.json();
      setScanResult(`Resolved ${data.resolved || 0} of ${data.checked || 0} trades`);
      await fetchProfiles();
    } catch (e) {
      setScanResult(`Error: ${e instanceof Error ? e.message : "unknown"}`);
    } finally {
      setResolving(false);
    }
  }, [fetchProfiles]);

  useEffect(() => {
    fetchProfiles();
    // Auto-refresh every 30s
    const interval = setInterval(fetchProfiles, 30000);
    return () => clearInterval(interval);
  }, [fetchProfiles]);

  if (loading && profiles.length === 0) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <Activity className="w-12 h-12 animate-pulse text-primary" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Trophy className="w-8 h-8 text-yellow-500" />
            <div>
              <h1 className="text-2xl font-bold">PolyBot Profiles</h1>
              <p className="text-xs text-muted-foreground">3 estrategias competindo por maxima assertividade</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => runScan("all")}
              disabled={scanning !== null}
              className="px-4 py-2 bg-yellow-500 text-black rounded-md text-sm font-medium hover:bg-yellow-400 disabled:opacity-50 flex items-center gap-2"
            >
              {scanning === "all" ? <Activity className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              Scan All
            </button>
            <button
              onClick={resolveAll}
              disabled={resolving}
              className="px-3 py-2 bg-muted hover:bg-muted/70 rounded-md text-sm flex items-center gap-2"
            >
              {resolving ? <Activity className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}
              Resolve
            </button>
            <button onClick={fetchProfiles} className="p-2 hover:bg-muted rounded-md">
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-6 space-y-4">
        {scanResult && (
          <Card className="border-yellow-500/30">
            <CardContent className="py-3">
              <p className="text-sm">{scanResult}</p>
            </CardContent>
          </Card>
        )}

        {/* 3 Profile Comparison Cards */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {profiles.map((profile) => {
            const portfolio = profile.portfolio || {};
            const balance = (portfolio.total_balance as number) || 1000;
            const pnl = (portfolio.total_pnl as number) || 0;
            const wins = profile.stats.wins;
            const losses = profile.stats.losses;
            const winRate = profile.stats.win_rate;

            return (
              <Card key={profile.name} className={`${profileColor(profile.name)} border-2`}>
                <CardContent className="pt-4">
                  {/* Header */}
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <ProfileIcon name={profile.name} />
                      <h2 className="text-xl font-bold">{profile.display_name}</h2>
                    </div>
                    <Badge variant="secondary" className="text-xs">
                      {profile.stats.total_trades} trades
                    </Badge>
                  </div>

                  {/* Description */}
                  <p className="text-xs text-muted-foreground mb-4">{profile.description}</p>

                  {/* Stats */}
                  <div className="grid grid-cols-2 gap-2 mb-4">
                    <div className="bg-muted/30 rounded p-2">
                      <div className="text-xs text-muted-foreground">Balance</div>
                      <div className="text-lg font-bold">{formatUSD(balance)}</div>
                    </div>
                    <div className="bg-muted/30 rounded p-2">
                      <div className="text-xs text-muted-foreground">P&L</div>
                      <div className={`text-lg font-bold ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {pnl >= 0 ? "+" : ""}{formatUSD(pnl)}
                      </div>
                    </div>
                    <div className="bg-muted/30 rounded p-2">
                      <div className="text-xs text-muted-foreground">Win Rate</div>
                      <div className={`text-lg font-bold ${winRate >= 90 ? "text-emerald-400" : winRate >= 70 ? "text-yellow-400" : "text-muted-foreground"}`}>
                        {winRate.toFixed(0)}%
                      </div>
                    </div>
                    <div className="bg-muted/30 rounded p-2">
                      <div className="text-xs text-muted-foreground">W / L</div>
                      <div className="text-lg font-bold">
                        <span className="text-emerald-400">{wins}</span>
                        <span className="text-muted-foreground">/</span>
                        <span className="text-red-400">{losses}</span>
                      </div>
                    </div>
                  </div>

                  {/* Settings */}
                  <div className="text-xs text-muted-foreground space-y-1 mb-4 bg-muted/20 p-2 rounded">
                    <div>Min Edge: <span className="text-foreground font-mono">{(profile.settings.min_edge * 100).toFixed(0)}%</span></div>
                    <div>Min Confidence: <span className="text-foreground font-mono">{(profile.settings.min_confidence * 100).toFixed(0)}%</span></div>
                    <div>Bet Size: <span className="text-foreground font-mono">${profile.settings.bet_size}</span></div>
                    <div>Verdicts: <span className="text-foreground font-mono">{profile.settings.required_verdict.join(", ")}</span></div>
                  </div>

                  {/* Run button */}
                  <button
                    onClick={() => runScan(profile.name)}
                    disabled={scanning !== null}
                    className="w-full py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 mb-3"
                  >
                    {scanning === profile.name ? (
                      <><Activity className="w-4 h-4 animate-spin" /> Scanning...</>
                    ) : (
                      <><Zap className="w-4 h-4" /> Run {profile.display_name}</>
                    )}
                  </button>

                  {/* Recent trades */}
                  {profile.recent_trades.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-xs font-medium text-muted-foreground mb-1">Recent Trades</div>
                      {profile.recent_trades.slice(0, 3).map((trade) => (
                        <div key={trade.id} className="bg-muted/20 p-2 rounded text-xs">
                          <div className="flex items-center justify-between mb-1">
                            <Badge className={
                              trade.status === "won" ? "bg-emerald-500/20 text-emerald-400" :
                              trade.status === "lost" ? "bg-red-500/20 text-red-400" :
                              "bg-yellow-500/20 text-yellow-400"
                            }>
                              {trade.status}
                            </Badge>
                            <span className={`font-bold ${
                              (trade.pnl ?? 0) > 0 ? "text-emerald-400" :
                              (trade.pnl ?? 0) < 0 ? "text-red-400" : ""
                            }`}>
                              {trade.pnl !== null && trade.pnl !== undefined
                                ? `${trade.pnl >= 0 ? "+" : ""}${formatUSD(trade.pnl)}`
                                : formatUSD(trade.cost)}
                            </span>
                          </div>
                          <p className="line-clamp-2 text-muted-foreground">{trade.question || "Unknown"}</p>
                          <div className="flex items-center gap-1 mt-1">
                            {trade.direction === "yes" ? (
                              <TrendingUp className="w-3 h-3 text-emerald-400" />
                            ) : (
                              <TrendingDown className="w-3 h-3 text-red-400" />
                            )}
                            <span className="text-muted-foreground">
                              {(trade.price * 100).toFixed(0)}%
                            </span>
                            {trade.edge !== undefined && trade.edge > 0 && (
                              <span className="text-blue-400 ml-auto">
                                +{(trade.edge * 100).toFixed(1)}% edge
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </main>
    </div>
  );
}
