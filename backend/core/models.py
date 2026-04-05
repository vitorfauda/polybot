from sqlalchemy import Column, String, Float, Integer, DateTime, Text, Boolean, JSON, Enum as SQLEnum
from sqlalchemy.sql import func
from .database import Base
import enum


class MarketStatus(str, enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"


class TradeStatus(str, enum.Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    SIMULATED = "simulated"


class TradeSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class Market(Base):
    __tablename__ = "markets"

    id = Column(String, primary_key=True)
    condition_id = Column(String, index=True)
    token_id_yes = Column(String)
    token_id_no = Column(String)
    question = Column(Text, nullable=False)
    category = Column(String, index=True)
    end_date = Column(DateTime)
    volume = Column(Float, default=0)
    liquidity = Column(Float, default=0)
    current_price_yes = Column(Float)
    current_price_no = Column(Float)
    status = Column(SQLEnum(MarketStatus), default=MarketStatus.ACTIVE, index=True)
    metadata_json = Column(JSON, default={})
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    url = Column(String)
    content_summary = Column(Text)
    published_at = Column(DateTime)
    sentiment_vader = Column(Float)
    sentiment_label = Column(String)
    relevance_score = Column(Float)
    related_market_ids = Column(JSON, default=[])
    created_at = Column(DateTime, server_default=func.now())


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String, index=True)
    news_ids = Column(JSON, default=[])
    llm_analysis = Column(Text)
    confidence_score = Column(Float)
    predicted_direction = Column(String)  # "yes" or "no"
    predicted_probability = Column(Float)
    market_price = Column(Float)
    edge = Column(Float)
    recommended_action = Column(String)  # "buy_yes", "buy_no", "hold"
    recommended_size = Column(Float)
    kelly_fraction = Column(Float)
    created_at = Column(DateTime, server_default=func.now())


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String, index=True)
    analysis_id = Column(Integer)
    side = Column(SQLEnum(TradeSide))
    token_id = Column(String)
    price = Column(Float)
    size = Column(Float)
    cost = Column(Float)
    order_type = Column(String, default="limit")
    status = Column(SQLEnum(TradeStatus), default=TradeStatus.SIMULATED)
    pnl = Column(Float)
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())


class Portfolio(Base):
    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True, autoincrement=True)
    total_balance = Column(Float, default=0)
    invested = Column(Float, default=0)
    available = Column(Float, default=0)
    total_pnl = Column(Float, default=0)
    win_count = Column(Integer, default=0)
    loss_count = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
