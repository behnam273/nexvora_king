from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import SignalTrade
from app.security import sanitize_text, validate_external_url
from app.services.analytics import compute_performance_analytics
from app.services.news_engine import _dedupe_hash, score_news_item


def _make_memory_db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def test_kpi_reconciliation_excludes_open_and_cancelled():
    db = _make_memory_db()
    rows = [
        # 2 WINS (one hit TP1+TP2 -> 2 target hits, still 1 winning trade!)
        SignalTrade(
            trade_code="T1", idempotency_key="k1", symbol="EURUSD", timeframe="4H", risk_tier="SAFE",
            direction="LONG", entry_module="SWEEP", status="CLOSED_WIN", outcome="WIN",
            entry_price=1.1, current_price=1.12, initial_sl=1.09, current_sl=1.11, tp1=1.11, tp2=1.12, tp3=1.13,
            tp1_hit=True, tp2_hit=True, confluence_score=9.0, realized_r=2.1, realized_pnl_usd=210.0,
        ),
        SignalTrade(
            trade_code="T2", idempotency_key="k2", symbol="XAUUSD", timeframe="15m", risk_tier="MEDIUM_RISK",
            direction="SHORT", entry_module="CHoCH", status="CLOSED_WIN", outcome="WIN",
            entry_price=2660, current_price=2640, initial_sl=2670, current_sl=2660, tp1=2640, tp2=2630, tp3=2610,
            tp1_hit=True, confluence_score=8.5, realized_r=1.0, realized_pnl_usd=100.0,
        ),
        # 1 LOSS
        SignalTrade(
            trade_code="T3", idempotency_key="k3", symbol="GBPUSD", timeframe="5m", risk_tier="HIGH_RISK",
            direction="LONG", entry_module="SWEEP", status="CLOSED_LOSS", outcome="LOSS",
            entry_price=1.26, current_price=1.25, initial_sl=1.25, current_sl=1.25, tp1=1.28, tp2=1.29, tp3=1.31,
            confluence_score=8.5, realized_r=-1.0, realized_pnl_usd=-100.0,
        ),
        # 1 BREAK-EVEN
        SignalTrade(
            trade_code="T4", idempotency_key="k4", symbol="USDJPY", timeframe="4H", risk_tier="SAFE",
            direction="LONG", entry_module="FLIP", status="CLOSED_BE", outcome="BE",
            entry_price=150, current_price=150, initial_sl=149, current_sl=150, tp1=152, tp2=153, tp3=155,
            confluence_score=8.2, realized_r=0.0, realized_pnl_usd=0.0,
        ),
        # 1 OPEN & 1 CANCELLED -> MUST BE EXCLUDED from denominator!
        SignalTrade(
            trade_code="T5", idempotency_key="k5", symbol="AUDUSD", timeframe="4H", risk_tier="SAFE",
            direction="LONG", entry_module="SWEEP", status="ACTIVE", outcome="OPEN",
            entry_price=0.65, current_price=0.655, initial_sl=0.645, current_sl=0.645, tp1=0.66, tp2=0.665, tp3=0.675,
            confluence_score=8.4, realized_r=0.0, realized_pnl_usd=0.0,
        ),
        SignalTrade(
            trade_code="T6", idempotency_key="k6", symbol="EURGBP", timeframe="15m", risk_tier="MEDIUM_RISK",
            direction="SHORT", entry_module="CHoCH", status="EXPIRED", outcome="CANCELLED",
            entry_price=0.85, current_price=0.852, initial_sl=0.855, current_sl=0.855, tp1=0.84, tp2=0.835, tp3=0.825,
            confluence_score=8.1, realized_r=0.0, realized_pnl_usd=0.0,
        ),
    ]
    db.add_all(rows)
    db.commit()

    res = compute_performance_analytics(db)
    kpi = res["kpis"]
    assert kpi["total_trades"] == 4          # 2 WIN + 1 LOSS + 1 BE (OPEN & CANCELLED excluded)
    assert kpi["winning_trades"] == 2
    assert kpi["losing_trades"] == 1
    assert kpi["breakeven_trades"] == 1
    assert kpi["win_rate"] == 50.0           # 2 / 4 * 100
    assert kpi["target_hits_total"] == 3     # TP1(2) + TP2(1) != winning_trades(2)
    assert kpi["gross_profit_usd"] == 310.0
    assert kpi["gross_loss_usd"] == 100.0
    assert kpi["net_profit_usd"] == 210.0
    assert kpi["profit_factor"] == 3.1
    db.close()


def test_news_scoring_dedup_xss_and_ssrf_guard():
    # SSRF checks
    assert validate_external_url("http://127.0.0.1:8000/admin") is False
    assert validate_external_url("http://169.254.169.254/latest/meta-data") is False
    assert validate_external_url("http://10.0.0.5/internal") is False
    assert validate_external_url("file:///etc/passwd") is False
    assert validate_external_url("https://www.fxstreet.com/rss/news", {"www.fxstreet.com"}) is True
    assert validate_external_url("https://evil.example.com/rss", {"www.fxstreet.com"}) is False

    # XSS sanitization
    dirty = '<script>alert("xss")</script><b>Federal Reserve</b> holds rates'
    assert "<script>" not in sanitize_text(dirty)
    assert "Federal Reserve holds rates" == sanitize_text(dirty)

    # Deduplication hash consistency
    assert _dedupe_hash("Fed holds rates steady!") == _dedupe_hash("fed holds rates steady")

    # Independent 5 scores + active trade risk boost
    sc_open = score_news_item(
        "Federal Reserve interest rate decision shakes USD and Gold XAU/USD",
        "Hawkish statement beats forecast",
        source_type="official_institution",
        active_trade_symbols={"XAUUSD", "EURUSD"},
    )
    sc_flat = score_news_item(
        "Federal Reserve interest rate decision shakes USD and Gold XAU/USD",
        "Hawkish statement beats forecast",
        source_type="official_institution",
        active_trade_symbols=set(),
    )
    assert sc_open["impact_level"] == "HIGH"
    assert sc_open["market_impact_pct"] >= 80
    assert sc_open["active_trade_risk_score"] > sc_flat["active_trade_risk_score"]
    assert "XAUUSD" in sc_open["related_symbols"]


def test_rss_duplicate_headlines_in_same_batch_never_raise_integrity_error(monkeypatch):
    """Regression test for real Federal Reserve RSS feeds containing repeated FOMC headlines."""
    import httpx
    from app.models import NewsItem
    from app.services import news_engine

    rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <title>Federal Reserve</title>
      <item>
        <title>Federal Reserve issues FOMC statement</title>
        <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm</link>
        <pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate>
        <description>Federal Reserve issues FOMC statement</description>
      </item>
      <item>
        <title>Federal Reserve issues FOMC statement</title>
        <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm</link>
        <pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate>
        <description>Duplicate entry on the same day</description>
      </item>
      <item>
        <title>Federal Reserve issues FOMC statement</title>
        <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20261105a.htm</link>
        <pubDate>Thu, 05 Nov 2026 19:00:00 GMT</pubDate>
        <description>Next month FOMC statement</description>
      </item>
    </channel></rss>"""

    class DummyResp:
        status_code = 200
        content = rss_xml

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return DummyResp()

    monkeypatch.setattr(httpx, "Client", DummyClient)
    monkeypatch.setattr(
        news_engine,
        "NEWS_SOURCES",
        [
            {
                "key": "fed_press",
                "name": "Federal Reserve (Official)",
                "type": "official_institution",
                "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
            }
        ],
    )
    monkeypatch.setattr(news_engine, "get_settings", lambda: type("S", (), {"nexvora_data_mode": "live", "llm_api_key": "", "llm_api_base_url": ""})())

    db = _make_memory_db()
    items = news_engine.fetch_and_ingest_news(db)
    # Two distinct dates inserted, same-day duplicate cleanly skipped without IntegrityError/PendingRollbackError
    assert len(items) == 2
    assert db.query(NewsItem).count() == 2
    assert "بیانیه سیاست پولی FOMC" in items[0].persian_title

    # Running again must also be idempotent with 0 errors
    items_again = news_engine.fetch_and_ingest_news(db)
    assert len(items_again) == 0
    assert db.query(NewsItem).count() == 2
    db.close()

