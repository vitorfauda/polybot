from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str = ""

    # Polymarket
    polymarket_host: str = "https://clob.polymarket.com"
    polymarket_private_key: str = ""
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_api_passphrase: str = ""
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    data_api_url: str = "https://data-api.polymarket.com"

    # Claude
    anthropic_api_key: str = ""

    # News
    newsapi_key: str = ""
    fred_api_key: str = ""

    # Risk defaults
    max_position_pct: float = 0.05  # max 5% of portfolio per trade
    kelly_fraction: float = 0.25  # quarter Kelly
    min_edge: float = 0.05  # minimum 5% edge to trade
    max_open_positions: int = 10

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
