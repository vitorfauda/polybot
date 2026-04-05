"""PolyBot API - Main FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.routes import markets, analysis, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[PolyBot] Starting up...")
    yield
    # Shutdown
    print("[PolyBot] Shutting down...")


app = FastAPI(
    title="PolyBot API",
    description="AI-powered prediction market analysis for Polymarket",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(markets.router, prefix="/api/markets", tags=["markets"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "polybot"}
