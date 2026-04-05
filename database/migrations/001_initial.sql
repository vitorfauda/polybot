-- PolyBot Database Schema
-- Run this on Supabase SQL Editor

CREATE TABLE IF NOT EXISTS markets (
  id TEXT PRIMARY KEY,
  condition_id TEXT,
  token_id_yes TEXT,
  token_id_no TEXT,
  question TEXT NOT NULL,
  category TEXT,
  end_date TIMESTAMPTZ,
  volume DOUBLE PRECISION DEFAULT 0,
  liquidity DOUBLE PRECISION DEFAULT 0,
  current_price_yes DOUBLE PRECISION,
  current_price_no DOUBLE PRECISION,
  status TEXT DEFAULT 'active',
  metadata_json JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS news (
  id SERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  content_summary TEXT,
  published_at TIMESTAMPTZ,
  sentiment_vader DOUBLE PRECISION,
  sentiment_label TEXT,
  relevance_score DOUBLE PRECISION,
  related_market_ids JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analyses (
  id SERIAL PRIMARY KEY,
  market_id TEXT REFERENCES markets(id),
  news_ids JSONB DEFAULT '[]',
  llm_analysis TEXT,
  confidence_score DOUBLE PRECISION,
  predicted_direction TEXT,
  predicted_probability DOUBLE PRECISION,
  market_price DOUBLE PRECISION,
  edge DOUBLE PRECISION,
  recommended_action TEXT,
  recommended_size DOUBLE PRECISION,
  kelly_fraction DOUBLE PRECISION,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trades (
  id SERIAL PRIMARY KEY,
  market_id TEXT,
  analysis_id INTEGER REFERENCES analyses(id),
  side TEXT,
  direction TEXT,
  token_id TEXT,
  price DOUBLE PRECISION,
  size DOUBLE PRECISION,
  cost DOUBLE PRECISION,
  order_type TEXT DEFAULT 'limit',
  status TEXT DEFAULT 'simulated',
  pnl DOUBLE PRECISION,
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portfolio (
  id SERIAL PRIMARY KEY,
  total_balance DOUBLE PRECISION DEFAULT 1000,
  invested DOUBLE PRECISION DEFAULT 0,
  available DOUBLE PRECISION DEFAULT 1000,
  total_pnl DOUBLE PRECISION DEFAULT 0,
  win_count INTEGER DEFAULT 0,
  loss_count INTEGER DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert initial portfolio
INSERT INTO portfolio (total_balance, invested, available, total_pnl)
VALUES (1000, 0, 1000, 0);

-- Indexes
CREATE INDEX idx_markets_status ON markets(status);
CREATE INDEX idx_markets_category ON markets(category);
CREATE INDEX idx_news_published ON news(published_at DESC);
CREATE INDEX idx_analyses_market ON analyses(market_id);
CREATE INDEX idx_trades_market ON trades(market_id);
CREATE INDEX idx_trades_status ON trades(status);
