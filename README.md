# PolyBot

AI-powered prediction market analysis and trading system for Polymarket.

## Features

- **Real-time market data** from Polymarket API (Gamma + CLOB)
- **News pipeline** collecting from Google News RSS, Reuters, BBC, CoinDesk, and more
- **Sentiment analysis** using VADER NLP
- **Opportunity scoring** combining market data, news sentiment, and edge calculation
- **Kelly Criterion position sizing** with fractional Kelly for risk management
- **Visual dashboard** built with Next.js + shadcn/ui

## Quick Start

### Backend

```bash
cd backend
python -m venv venv
source venv/Scripts/activate  # Windows
# source venv/bin/activate    # Mac/Linux
pip install -r requirements.txt
cp .env.example .env
uvicorn api.main:app --reload
```

API runs at `http://localhost:8000` (docs at `/docs`)

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard runs at `http://localhost:3000`

## Architecture

```
Backend (Python/FastAPI)          Frontend (Next.js)
├── Polymarket API Client         ├── Dashboard Overview
├── News Pipeline (RSS/Google)    ├── Market Browser
├── Sentiment Analysis (VADER)    ├── Opportunities Scanner
├── Opportunity Scorer            └── News Feed
├── Kelly Position Sizer
└── REST API
```

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/health` | Health check |
| `GET /api/markets/` | List active markets |
| `GET /api/markets/search?q=` | Search markets |
| `GET /api/markets/{id}/history` | Price history |
| `GET /api/analysis/news` | Latest news with sentiment |
| `GET /api/analysis/scan` | Scan for opportunities |
| `GET /api/analysis/kelly` | Calculate position sizing |
| `GET /api/dashboard/overview` | Dashboard data |
