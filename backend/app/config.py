from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Strict allowed Forex + Gold instruments requested by user
ALLOWED_SYMBOLS: List[str] = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "EURGBP",
    "XAUUSD",
]

SYMBOL_META: Dict[str, dict] = {
    "EURUSD": {
        "display": "EUR/USD",
        "name_fa": "یورو / دلار آمریکا",
        "market_class": "FOREX",
        "base": "EUR",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "point_value": 100000.0,
        "corr_group": "EUR_GBP_USD",
        "twelve_data": "EUR/USD",
        "yahoo": "EURUSD=X",
        "base_price_demo": 1.0845,
        "vol_demo": 0.00055,
    },
    "GBPUSD": {
        "display": "GBP/USD",
        "name_fa": "پوند انگلیس / دلار آمریکا",
        "market_class": "FOREX",
        "base": "GBP",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "point_value": 100000.0,
        "corr_group": "EUR_GBP_USD",
        "twelve_data": "GBP/USD",
        "yahoo": "GBPUSD=X",
        "base_price_demo": 1.2685,
        "vol_demo": 0.00068,
    },
    "USDJPY": {
        "display": "USD/JPY",
        "name_fa": "دلار آمریکا / ین ژاپن",
        "market_class": "FOREX",
        "base": "USD",
        "quote": "JPY",
        "pip_size": 0.01,
        "digits": 3,
        "point_value": 100000.0,
        "corr_group": "JPY_GROUP",
        "twelve_data": "USD/JPY",
        "yahoo": "USDJPY=X",
        "base_price_demo": 153.40,
        "vol_demo": 0.095,
    },
    "AUDUSD": {
        "display": "AUD/USD",
        "name_fa": "دلار استرالیا / دلار آمریکا",
        "market_class": "FOREX",
        "base": "AUD",
        "quote": "USD",
        "pip_size": 0.0001,
        "digits": 5,
        "point_value": 100000.0,
        "corr_group": "AUD_GROUP",
        "twelve_data": "AUD/USD",
        "yahoo": "AUDUSD=X",
        "base_price_demo": 0.6540,
        "vol_demo": 0.00048,
    },
    "EURGBP": {
        "display": "EUR/GBP",
        "name_fa": "یورو / پوند انگلیس",
        "market_class": "FOREX",
        "base": "EUR",
        "quote": "GBP",
        "pip_size": 0.0001,
        "digits": 5,
        "point_value": 100000.0,
        "corr_group": "EUR_GBP_USD",
        "twelve_data": "EUR/GBP",
        "yahoo": "EURGBP=X",
        "base_price_demo": 0.8550,
        "vol_demo": 0.00036,
    },
    "XAUUSD": {
        "display": "XAU/USD",
        "name_fa": "انس جهانی طلا / دلار",
        "market_class": "METALS",
        "base": "XAU",
        "quote": "USD",
        "pip_size": 0.1,
        "digits": 2,
        "point_value": 100.0,
        "corr_group": "METALS_GROUP",
        "twelve_data": "XAU/USD",
        "yahoo": "GC=F",
        "base_price_demo": 2665.00,
        "vol_demo": 2.40,
    },
}

# Exact 3 timeframes with explicit risk tier mapping requested by user
ALLOWED_TIMEFRAMES: List[str] = ["4H", "15m", "5m"]

TIMEFRAME_META: Dict[str, dict] = {
    "4H": {
        "label_fa": "۴ ساعته — حالت امن",
        "risk_tier": "SAFE",
        "risk_label_fa": "امن (ریسک کم)",
        "minutes": 240,
        "htf_primary": "1D",
        "htf_secondary": "1D",
        "twelve_data": "4h",
        "yahoo_interval": "1h",
        "yahoo_range": "60d",
        "default_min_score": 8.0,
        "pivot_len": 7,
        "require_session_filter": False,
        "cooldown_bars": 6,
        "arm_valid_bars": 20,
    },
    "15m": {
        "label_fa": "۱۵ دقیقه — ریسک متوسط",
        "risk_tier": "MEDIUM_RISK",
        "risk_label_fa": "ریسک متوسط",
        "minutes": 15,
        "htf_primary": "4H",
        "htf_secondary": "1D",
        "twelve_data": "15min",
        "yahoo_interval": "15m",
        "yahoo_range": "30d",
        "default_min_score": 8.0,
        "pivot_len": 6,
        "require_session_filter": True,
        "cooldown_bars": 10,
        "arm_valid_bars": 20,
    },
    "5m": {
        "label_fa": "۵ دقیقه — ریسک بالا",
        "risk_tier": "HIGH_RISK",
        "risk_label_fa": "ریسک بالا (فیلتر حداکثری)",
        "minutes": 5,
        "htf_primary": "1H",
        "htf_secondary": "4H",
        "twelve_data": "5min",
        "yahoo_interval": "5m",
        "yahoo_range": "14d",
        "default_min_score": 8.5,
        "pivot_len": 5,
        "require_session_filter": True,
        "cooldown_bars": 12,
        "arm_valid_bars": 18,
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    nexvora_env: Literal["development", "staging", "production"] = "development"
    nexvora_data_mode: Literal["live", "demo", "auto"] = "auto"

    database_url: str = "sqlite:///./nexvora.db"
    secret_key: str = "dev-only-change-in-production-nexvora-secret-key-64chars-min"
    session_ttl_hours: int = 24
    session_idle_minutes: int = 120
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("nexvora_env", mode="before")
    @classmethod
    def _normalize_env(cls, v):
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ("prod", "production"):
                return "production"
            if s in ("stage", "staging"):
                return "staging"
            if s in ("dev", "development", ""):
                return "development"
        return v

    @field_validator("nexvora_data_mode", mode="before")
    @classmethod
    def _normalize_data_mode(cls, v):
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ("live", "live_only", "real"):
                return "live"
            if s in ("demo", "demo_replay", "replay", "mock"):
                return "demo"
            if s in ("auto", "live_with_demo_fallback", "hybrid", ""):
                return "auto"
        return v

    @field_validator("cookie_samesite", mode="before")
    @classmethod
    def _normalize_samesite(cls, v):
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
        return "lax"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_empty_db_url(cls, v):
        if not v or (isinstance(v, str) and not v.strip()):
            if Path("/app/data").is_dir():
                return "sqlite:////app/data/nexvora.db"
            return "sqlite:///./nexvora.db"
        return v.strip() if isinstance(v, str) else v

    initial_admin_email: str = "admin@nexvora.local"
    initial_admin_password: str = "NexvoraAdmin!2026"

    twelve_data_api_key: str = ""
    twelve_data_api_keys: str = ""  # Optional comma-separated key pool for automatic rotation
    oanda_api_token: str = ""  # Free OANDA v20 Practice token (highest quality FX + XAUUSD)
    oanda_env: Literal["practice", "live"] = "practice"
    alpha_vantage_api_key: str = ""  # Optional additional FX backup
    market_data_providers: str = "oanda,biquote,twelvedata,yahoo,alphavantage"

    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    telegram_dry_run: bool = True

    @property
    def twelve_data_key_pool(self) -> List[str]:
        keys: List[str] = []
        for raw in (self.twelve_data_api_keys, self.twelve_data_api_key):
            for part in (raw or "").split(","):
                k = part.strip()
                if k and k not in keys:
                    keys.append(k)
        return keys

    @property
    def market_provider_order(self) -> List[str]:
        valid = {"oanda", "biquote", "twelvedata", "yahoo", "alphavantage"}
        out = [p.strip().lower() for p in (self.market_data_providers or "").split(",") if p.strip().lower() in valid]
        return out or ["oanda", "biquote", "twelvedata", "yahoo", "alphavantage"]

    llm_api_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    engine_scan_interval_sec: int = 120
    position_track_interval_sec: int = 30
    news_fetch_interval_sec: int = 300
    backtest_refresh_interval_sec: int = 3600

    pwa_public_url: str = "http://localhost:5173"
    railway_public_domain: str = ""

    @property
    def cors_origin_list(self) -> List[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if self.railway_public_domain:
            railway_origin = f"https://{self.railway_public_domain.strip()}"
            if railway_origin not in origins:
                origins.append(railway_origin)
        if self.pwa_public_url and self.pwa_public_url.startswith("http"):
            pub = self.pwa_public_url.rstrip("/")
            if pub not in origins:
                origins.append(pub)
        return origins

    @property
    def effective_public_url(self) -> str:
        if self.pwa_public_url and self.pwa_public_url != "http://localhost:5173":
            return self.pwa_public_url.rstrip("/")
        if self.railway_public_domain:
            return f"https://{self.railway_public_domain.strip()}"
        return self.pwa_public_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
