from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

import feedparser
import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import ALLOWED_SYMBOLS, SYMBOL_META, get_settings
from app.models import EconomicEvent, NewsItem, Notification, SignalTrade, SourceHealth, User, utcnow
from app.security import sanitize_text, validate_external_url

# Permitted financial publishers & official central bank primary feeds
NEWS_SOURCES = [
    {
        "key": "fxstreet_rss",
        "name": "FXStreet",
        "type": "publisher",
        "url": "https://www.fxstreet.com/rss/news",
        "host": "www.fxstreet.com",
    },
    {
        "key": "forexlive_rss",
        "name": "ForexLive",
        "type": "publisher",
        "url": "https://www.forexlive.com/feed/news",
        "host": "www.forexlive.com",
    },
    {
        "key": "investing_forex_rss",
        "name": "Investing.com",
        "type": "publisher",
        "url": "https://www.investing.com/rss/news_1.rss",
        "host": "www.investing.com",
    },
    {
        "key": "fed_official_rss",
        "name": "Federal Reserve (Official)",
        "type": "official_institution",
        "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "host": "www.federalreserve.gov",
    },
    {
        "key": "ecb_official_rss",
        "name": "European Central Bank (Official)",
        "type": "official_institution",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "host": "www.ecb.europa.eu",
    },
    {
        "key": "boe_official_rss",
        "name": "Bank of England (Official)",
        "type": "official_institution",
        "url": "https://www.bankofengland.co.uk/rss/news",
        "host": "www.bankofengland.co.uk",
    },
]

ALLOWED_NEWS_HOSTS = {s["host"] for s in NEWS_SOURCES}

CURRENCY_KEYWORDS: Dict[str, List[str]] = {
    "USD": ["usd", "dollar", "fed", "fomc", "powell", "us ", "u.s.", "treasury", "payroll", "nfp", "us cpi", "pce", "greenback"],
    "EUR": ["eur", "euro", "ecb", "lagarde", "eurozone", "germany", "german", "euro area", "eur/usd", "eurusd", "eurgbp"],
    "GBP": ["gbp", "pound", "sterling", "boe", "bank of england", "uk ", "u.k.", "britain", "bailey", "gbp/usd", "gbpusd"],
    "JPY": ["jpy", "yen", "boj", "bank of japan", "ueda", "tokyo", "japan", "usd/jpy", "usdjpy"],
    "AUD": ["aud", "aussie", "rba", "australia", "australian", "bullock", "aud/usd", "audusd"],
    "XAU": ["gold", "xau", "bullion", "precious metal", "xau/usd", "xauusd"],
}

CATEGORY_RULES: List[Tuple[str, List[str], int, int]] = [
    # (category, keywords, base_importance, base_volatility)
    ("central_bank", ["rate decision", "interest rate", "fomc", "fed ", "ecb", "boe", "boj", "rba", "powell", "lagarde", "monetary policy", "rate cut", "rate hike"], 92, 90),
    ("inflation", ["cpi", "inflation", "pce", "ppi", "consumer price", "core inflation"], 90, 88),
    ("employment", ["nfp", "nonfarm", "payroll", "unemployment", "jobless", "labor market", "wage"], 88, 86),
    ("gdp_growth", ["gdp", "pmi", "retail sales", "ism", "manufacturing", "recession", "growth"], 78, 74),
    ("geopolitics", ["tariff", "sanction", "war", "conflict", "oil spike", "geopolitic", "safe haven", "crisis"], 82, 84),
    ("gold_commodities", ["gold", "xau", "bullion", "treasury yield", "real yield"], 76, 78),
    ("forex_technical", ["breakout", "resistance", "support", "technical", "forecast", "rally", "drops", "slides"], 58, 55),
]

HAWKISH_BULL_WORDS = ["hawkish", "rate hike", "higher than expected", "beats forecast", "stronger", "surges", "rallies", "hotter inflation", "tightening", "rises"]
DOVISH_BEAR_WORDS = ["dovish", "rate cut", "lower than expected", "misses forecast", "weaker", "drops", "falls", "cooling inflation", "slowdown", "slumps"]

# Built-in Persian Forex NLP lexicon for offline/deterministic translation
FA_PHRASE_MAP: List[Tuple[str, str]] = [
    ("Federal Reserve", "فدرال رزرو آمریکا"),
    ("European Central Bank", "بانک مرکزی اروپا"),
    ("Bank of England", "بانک مرکزی انگلیس"),
    ("Bank of Japan", "بانک مرکزی ژاپن"),
    ("Reserve Bank of Australia", "بانک مرکزی استرالیا"),
    ("interest rate", "نرخ بهره"),
    ("rate cut", "کاهش نرخ بهره"),
    ("rate hike", "افزایش نرخ بهره"),
    ("holds rates steady", "نرخ بهره را بدون تغییر حفظ کرد"),
    ("inflation", "تورم"),
    ("CPI", "شاخص قیمت مصرف‌کننده (CPI)"),
    ("Core PCE", "شاخص تورم هسته PCE"),
    ("Nonfarm Payrolls", "اشتغال بخش غیرکشاورزی آمریکا (NFP)"),
    ("NFP", "گزارش اشتغال آمریکا (NFP)"),
    ("unemployment", "نرخ بیکاری"),
    ("GDP", "تولید ناخالص داخلی (GDP)"),
    ("PMI", "شاخص مدیران خرید (PMI)"),
    ("gold", "انس جهانی طلا"),
    ("XAU/USD", "طلا (XAU/USD)"),
    ("EUR/USD", "جفت‌ارز EUR/USD"),
    ("GBP/USD", "جفت‌ارز GBP/USD"),
    ("USD/JPY", "جفت‌ارز USD/JPY"),
    ("AUD/USD", "جفت‌ارز AUD/USD"),
    ("EUR/GBP", "جفت‌ارز EUR/GBP"),
    ("US Dollar", "دلار آمریکا"),
    ("Dollar", "دلار آمریکا"),
    ("Euro", "یورو"),
    ("Pound", "پوند انگلیس"),
    ("Yen", "ین ژاپن"),
    ("hawkish", "انقباضی (هاوکیش)"),
    ("dovish", "انبساطی (داویش)"),
    ("Treasury yields", "بازده اوراق خزانه‌داری آمریکا"),
    ("safe-haven", "دارایی امن"),
    ("issues FOMC statement", "بیانیه سیاست پولی FOMC را منتشر کرد"),
    ("FOMC statement", "بیانیه سیاست پولی FOMC"),
    ("Federal Reserve Board", "هیئت‌مدیره فدرال رزرو"),
    ("Monetary Policy Statement", "بیانیه سیاست پولی"),
    ("monetary policy decision", "تصمیم سیاست پولی"),
    ("press release", "اطلاعیه رسمی"),
    ("announces", "اعلام کرد"),
    ("minutes", "صورت‌جلسه"),
]

CATEGORY_FA = {
    "central_bank": "بانک مرکزی و نرخ بهره",
    "inflation": "تورم و شاخص قیمت",
    "employment": "بازار کار و اشتغال",
    "gdp_growth": "رشد اقتصادی و PMI",
    "geopolitics": "ژئوپلیتیک و ریسک جهانی",
    "gold_commodities": "طلا و کالاها",
    "forex_technical": "تحلیل و نوسانات فارکس",
    "macro": "اقتصاد کلان",
}


def _dedupe_hash(headline: str, pub_day: str = "") -> str:
    norm = re.sub(r"[^a-z0-9]+", " ", headline.lower()).strip()
    if pub_day:
        norm = f"{norm}|{pub_day}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:40]


def _detect_currencies_and_symbols(text: str) -> Tuple[List[str], List[str]]:
    tl = text.lower()
    currencies: List[str] = []
    for cur, kws in CURRENCY_KEYWORDS.items():
        if any(k in tl for k in kws):
            currencies.append(cur)
    if not currencies:
        currencies = ["USD"]

    symbols: List[str] = []
    for sym in ALLOWED_SYMBOLS:
        meta = SYMBOL_META[sym]
        if meta["base"] in currencies or meta["quote"] in currencies:
            symbols.append(sym)
    return currencies, symbols


def _translate_to_persian_offline(headline: str, summary_en: str, category: str, currencies: List[str]) -> Tuple[str, str]:
    title_fa = headline
    for en, fa in FA_PHRASE_MAP:
        title_fa = re.sub(re.escape(en), fa, title_fa, flags=re.IGNORECASE)

    # Ensure Persian framing so headline is clearly readable in RTL Persian UI
    cat_label = CATEGORY_FA.get(category, "خبر بازار مالی")
    cur_str = "، ".join(currencies)
    if not re.search(r"[\u0600-\u06FF]", title_fa):
        title_fa = f"گزارش {cat_label} ({cur_str}): {headline}"

    clean_sum = sanitize_text(summary_en)[:260]
    for en, fa in FA_PHRASE_MAP:
        clean_sum = re.sub(re.escape(en), fa, clean_sum, flags=re.IGNORECASE)

    summary_fa = (
        f"خلاصه هوشمند ({cat_label} — مرتبط با {cur_str}): "
        f"{clean_sum if clean_sum else title_fa}. "
        f"این خلاصه به‌صورت خودکار برای پایش ریسک بازار تولید شده و جایگزین متن اصلی ناشر نیست."
    )
    return title_fa[:280], summary_fa[:600]


def _translate_with_optional_llm(headline: str, summary_en: str, category: str, currencies: List[str]) -> Tuple[str, str]:
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_api_base_url:
        return _translate_to_persian_offline(headline, summary_en, category, currencies)
    if not validate_external_url(settings.llm_api_base_url):
        return _translate_to_persian_offline(headline, summary_en, category, currencies)
    try:
        prompt = (
            "Translate this financial news headline and short summary into concise, objective Persian for Forex traders. "
            "Do NOT fabricate numbers or facts. Return JSON with keys persian_title and persian_summary.\n"
            f"Headline: {headline}\nSummary: {summary_en[:400]}"
        )
        with httpx.Client(timeout=8.0, follow_redirects=False) as client:
            resp = client.post(
                f"{settings.llm_api_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                if parsed.get("persian_title") and parsed.get("persian_summary"):
                    return str(parsed["persian_title"])[:280], str(parsed["persian_summary"])[:600]
    except Exception:
        pass
    return _translate_to_persian_offline(headline, summary_en, category, currencies)


def score_news_item(
    headline: str,
    summary_en: str,
    source_type: str,
    active_trade_symbols: set[str],
) -> dict:
    """
    Computes 5 independent scores (per NEWS_INTELLIGENCE_SPEC.md) + unified Market Impact %:
    1. importance_score (0-100)
    2. volatility_score (0-100)
    3. currency_relevance_score (0-100)
    4. direction_bias + direction_confidence (0-100)
    5. active_trade_risk_score (0-100)
    """
    text = f"{headline} {summary_en}".lower()
    currencies, symbols = _detect_currencies_and_symbols(text)

    category = "macro"
    importance = 60
    volatility = 55
    for cat, kws, imp, vol in CATEGORY_RULES:
        if any(k in text for k in kws):
            category = cat
            importance = imp
            volatility = vol
            break

    # Primary official central bank releases carry higher structural importance
    if source_type == "official_institution":
        importance = min(98, importance + 6)
        volatility = min(96, volatility + 5)

    # Relevance to our exact 6 symbols
    currency_relevance = min(100, 45 + len(symbols) * 14)

    # Direction heuristic (transparent & conservative)
    bull_hits = sum(1 for w in HAWKISH_BULL_WORDS if w in text)
    bear_hits = sum(1 for w in DOVISH_BEAR_WORDS if w in text)
    if bull_hits > bear_hits and bull_hits > 0:
        direction_bias = "BULLISH"
        direction_conf = min(82, 48 + (bull_hits - bear_hits) * 14)
    elif bear_hits > bull_hits and bear_hits > 0:
        direction_bias = "BEARISH"
        direction_conf = min(82, 48 + (bear_hits - bull_hits) * 14)
    elif bull_hits > 0 and bear_hits > 0:
        direction_bias = "MIXED"
        direction_conf = 35
    else:
        direction_bias = "INSUFFICIENT_EVIDENCE"
        direction_conf = 20

    # Active trade risk: checks overlap with currently OPEN trades without modifying them
    overlapping = [s for s in symbols if s in active_trade_symbols]
    if overlapping:
        active_risk = min(100, int(0.6 * volatility + 0.4 * importance))
    else:
        active_risk = max(0, int(volatility * 0.25))

    # Weighted Market Impact % (clearly documented formula)
    market_impact_pct = int(round(0.45 * importance + 0.35 * volatility + 0.20 * currency_relevance))
    market_impact_pct = max(10, min(99, market_impact_pct))

    if market_impact_pct >= 75:
        impact_level = "HIGH"
    elif market_impact_pct >= 55:
        impact_level = "MEDIUM"
    else:
        impact_level = "LOW"

    methodology_fa = (
        f"فرمول درصد تاثیر ({market_impact_pct}%): ۴۵٪ اهمیت رویداد ({importance}) + "
        f"۳۵٪ پتانسیل نوسان ({volatility}) + ۲۰٪ ارتباط با ۶ جفت‌ارز NEXVORA ({currency_relevance}). "
        f"این شاخص تخمین تحلیلی است و تضمین حرکت قطعی قیمت نیست."
    )

    return {
        "category": category,
        "related_currencies": currencies,
        "related_symbols": symbols,
        "impact_level": impact_level,
        "market_impact_pct": market_impact_pct,
        "importance_score": importance,
        "volatility_score": volatility,
        "currency_relevance_score": currency_relevance,
        "direction_bias": direction_bias,
        "direction_confidence": direction_conf,
        "active_trade_risk_score": active_risk,
        "methodology_note_fa": methodology_fa,
    }


def _record_news_health(
    db: Session,
    key: str,
    name: str,
    status_str: str,
    latency_ms: Optional[int] = None,
    error_msg: str = "",
) -> None:
    row = db.query(SourceHealth).filter(SourceHealth.source_key == key).first()
    if not row:
        row = SourceHealth(
            source_key=key,
            source_type="news",
            display_name=name,
            rate_limit_note="Public RSS / Official press feed",
        )
        db.add(row)
    row.status = status_str
    row.requests_count = (row.requests_count or 0) + 1
    if latency_ms is not None:
        row.latency_ms = latency_ms
    if status_str == "HEALTHY":
        row.last_success_at = utcnow()
        row.last_error_msg = ""
    elif error_msg:
        row.last_error_at = utcnow()
        row.last_error_msg = error_msg[:400]
        row.failure_count = (row.failure_count or 0) + 1
    db.commit()


def _get_active_trade_symbols(db: Session) -> set[str]:
    rows = (
        db.query(SignalTrade.symbol)
        .filter(SignalTrade.status.in_(["PENDING_LIMIT", "ACTIVE", "TP1_HIT", "TP2_HIT"]))
        .all()
    )
    return {r[0] for r in rows}


def _seed_labelled_demo_news_and_calendar(db: Session, active_symbols: set[str]) -> List[NewsItem]:
    """
    Clearly labelled offline DEMO/REPLAY news & economic calendar fixtures used ONLY
    when live RSS feeds are unreachable (e.g. sandbox firewall). Every row carries
    `is_demo_data=True` so the UI explicitly labels them as non-live sample feed.
    """
    now = utcnow()
    sample_news = [
        {
            "source_name": "Federal Reserve (Official)",
            "source_type": "official_institution",
            "canonical_url": "https://www.federalreserve.gov/monetarypolicy.htm",
            "original_headline": "Federal Reserve signals data-dependent path as US Core PCE inflation stabilizes near target",
            "persian_title": "فدرال رزرو بر مسیر وابسته به داده تأکید کرد؛ تثبیت شاخص تورم هسته PCE آمریکا نزدیک هدف",
            "persian_summary": "کمیته بازار آزاد فدرال رزرو اعلام کرد تصمیمات آتی نرخ بهره به تداوم کاهش تورم هسته و داده‌های بازار کار وابسته است. این موضع‌گیری باعث افزایش نوسان لحظه‌ای روی دلار آمریکا، EUR/USD و انس جهانی طلا (XAU/USD) می‌شود.",
            "published_at": now - timedelta(minutes=18),
        },
        {
            "source_name": "European Central Bank (Official)",
            "source_type": "official_institution",
            "canonical_url": "https://www.ecb.europa.eu/press/html/index.en.html",
            "original_headline": "ECB policymakers highlight cautious stance on Eurozone interest rate cuts amid resilient wage growth",
            "persian_title": "سیاست‌گذاران بانک مرکزی اروپا نسبت به کاهش شتاب‌زده نرخ بهره در سایه رشد دستمزدها هشدار دادند",
            "persian_summary": "مقامات بانک مرکزی اروپا تأکید کردند که نرخ رشد دستمزد در منطقه یورو همچنان نیاز به رصد دقیق دارد. این بیانیه حمایت نسبی از یورو در برابر دلار (EUR/USD) و پوند (EUR/GBP) ایجاد کرده است.",
            "published_at": now - timedelta(minutes=42),
        },
        {
            "source_name": "FXStreet",
            "source_type": "publisher",
            "canonical_url": "https://www.fxstreet.com/news",
            "original_headline": "Gold XAU/USD tests key institutional liquidity zone as US Treasury yields retreat ahead of US CPI",
            "persian_title": "طلا (XAU/USD) در آستانه انتشار CPI آمریکا و افت بازده اوراق خزانه‌داری به ناحیه نقدینگی کلیدی رسید",
            "persian_summary": "افت بازده اوراق ۱۰ ساله آمریکا هم‌زمان با افزایش تقاضای دارایی امن باعث حرکت پرشتاب انس طلا شد. معامله‌گران در آستانه انتشار آمار تورم آمریکا باید ریسک اسپایک خبری را مدیریت کنند.",
            "published_at": now - timedelta(hours=1, minutes=15),
        },
        {
            "source_name": "ForexLive",
            "source_type": "publisher",
            "canonical_url": "https://www.forexlive.com/news",
            "original_headline": "Bank of Japan Governor Ueda reiterates vigilance on USD/JPY volatility and domestic inflation trend",
            "persian_title": "رئیس بانک مرکزی ژاپن (اوئدا) بر هوشیاری نسبت به نوسانات شدید USD/JPY و روند تورم داخلی تأکید کرد",
            "persian_summary": "اظهارات جدید رئیس بانک مرکزی ژاپن احتمال تعدیل سیاست پولی و مداخله کلامی روی ین را زنده نگه داشت که ریسک نوسان سریع روی جفت‌ارز USD/JPY را افزایش می‌دهد.",
            "published_at": now - timedelta(hours=2, minutes=10),
        },
        {
            "source_name": "Bank of England (Official)",
            "source_type": "official_institution",
            "canonical_url": "https://www.bankofengland.co.uk/news",
            "original_headline": "Bank of England Monetary Policy Summary notes UK services inflation remains closely monitored for GBP/USD",
            "persian_title": "گزارش سیاست پولی بانک مرکزی انگلیس: تورم بخش خدمات بریتانیا همچنان معیار کلیدی مسیر نرخ بهره است",
            "persian_summary": "بانک مرکزی انگلیس اعلام کرد تداوم تورم خدمات، زمان‌بندی تغییر نرخ بهره را تعیین می‌کند. این گزارش اثر مستقیم بر نوسانات GBP/USD و EUR/GBP در سشن لندن دارد.",
            "published_at": now - timedelta(hours=3, minutes=5),
        },
        {
            "source_name": "Investing.com",
            "source_type": "publisher",
            "canonical_url": "https://www.investing.com/news/forex-news",
            "original_headline": "AUD/USD reacts to Australian employment figures and Reserve Bank of Australia policy outlook",
            "persian_title": "واکنش جفت‌ارز AUD/USD به آمار اشتغال استرالیا و چشم‌انداز سیاست پولی بانک مرکزی استرالیا (RBA)",
            "persian_summary": "انتشار آمار اشتغال قوی‌تر از پیش‌بینی در استرالیا انتظارات برای حفظ نرخ بهره توسط RBA را تقویت کرد و تقاضا برای دلار استرالیا در برابر دلار آمریکا افزایش یافت.",
            "published_at": now - timedelta(hours=4, minutes=20),
        },
    ]

    created_items: List[NewsItem] = []
    for item in sample_news:
        h = _dedupe_hash(item["original_headline"])
        existing = db.query(NewsItem).filter(NewsItem.dedupe_hash == h).first()
        scores = score_news_item(item["original_headline"], item["persian_summary"], item["source_type"], active_symbols)
        if existing:
            existing.active_trade_risk_score = scores["active_trade_risk_score"]
            created_items.append(existing)
            continue
        row = NewsItem(
            dedupe_hash=h,
            source_name=item["source_name"],
            source_type=item["source_type"],
            canonical_url=item["canonical_url"],
            original_headline=item["original_headline"],
            persian_title=item["persian_title"],
            persian_summary=item["persian_summary"],
            summary_is_ai=True,
            category=scores["category"],
            related_currencies_json=json.dumps(scores["related_currencies"]),
            related_symbols_json=json.dumps(scores["related_symbols"]),
            impact_level=scores["impact_level"],
            market_impact_pct=scores["market_impact_pct"],
            importance_score=scores["importance_score"],
            volatility_score=scores["volatility_score"],
            currency_relevance_score=scores["currency_relevance_score"],
            direction_bias=scores["direction_bias"],
            direction_confidence=scores["direction_confidence"],
            active_trade_risk_score=scores["active_trade_risk_score"],
            methodology_note_fa=scores["methodology_note_fa"],
            published_at=item["published_at"],
            is_demo_data=True,
        )
        db.add(row)
        created_items.append(row)

    # Seed labelled sample economic calendar events covering our 6 instruments
    sample_events = [
        {
            "event_key": "us_cpi_yoy_next",
            "event_name_en": "US Core CPI (YoY)",
            "event_name_fa": "تورم هسته مصرف‌کننده آمریکا (CPI سالانه)",
            "country": "United States",
            "currency": "USD",
            "related_symbols": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"],
            "category": "inflation",
            "importance": "HIGH",
            "impact_pct": 95,
            "scheduled_at": now + timedelta(hours=3, minutes=30),
            "status": "SCHEDULED",
            "actual": None,
            "forecast": "3.2%",
            "previous": "3.3%",
            "surprise_note_fa": "رویداد پیش‌رو (زمان‌بندی‌شده) — ۳۰ دقیقه قبل و بعد گارد خبری موتور Trading Hub فعال می‌شود.",
            "source_name": "U.S. Bureau of Labor Statistics (BLS)",
            "source_url": "https://www.bls.gov/cpi/",
        },
        {
            "event_key": "ecb_rate_statement",
            "event_name_en": "ECB Interest Rate Decision & Press Conference",
            "event_name_fa": "تصمیم نرخ بهره بانک مرکزی اروپا (ECB) و نشست خبری",
            "country": "Euro Area",
            "currency": "EUR",
            "related_symbols": ["EURUSD", "EURGBP"],
            "category": "central_bank",
            "importance": "HIGH",
            "impact_pct": 93,
            "scheduled_at": now + timedelta(hours=7),
            "status": "SCHEDULED",
            "actual": None,
            "forecast": "3.25%",
            "previous": "3.25%",
            "surprise_note_fa": "تغییر لحن بیانیه لاگارد می‌تواند نوسان شدید روی EUR/USD و EUR/GBP ایجاد کند.",
            "source_name": "European Central Bank (ECB)",
            "source_url": "https://www.ecb.europa.eu/",
        },
        {
            "event_key": "uk_cpi_published",
            "event_name_en": "UK Services CPI (YoY)",
            "event_name_fa": "تورم بخش خدمات بریتانیا (سالانه)",
            "country": "United Kingdom",
            "currency": "GBP",
            "related_symbols": ["GBPUSD", "EURGBP"],
            "category": "inflation",
            "importance": "HIGH",
            "impact_pct": 87,
            "scheduled_at": now - timedelta(hours=2),
            "status": "PUBLISHED",
            "actual": "4.9%",
            "forecast": "4.8%",
            "previous": "4.9%",
            "surprise_note_fa": "عدد واقعی ۰.۱٪ بالاتر از پیش‌بینی منتشر شد؛ ریسک موضع انقباضی‌تر بانک مرکزی انگلیس را بالا برد.",
            "source_name": "UK Office for National Statistics (ONS)",
            "source_url": "https://www.ons.gov.uk/",
        },
        {
            "event_key": "boj_summary_opinions",
            "event_name_en": "BoJ Policy Rate Outlook & Tokyo Core CPI",
            "event_name_fa": "تورم هسته توکیو و چشم‌انداز نرخ بهره بانک مرکزی ژاپن",
            "country": "Japan",
            "currency": "JPY",
            "related_symbols": ["USDJPY"],
            "category": "central_bank",
            "importance": "HIGH",
            "impact_pct": 85,
            "scheduled_at": now + timedelta(hours=14),
            "status": "SCHEDULED",
            "actual": None,
            "forecast": "2.1%",
            "previous": "2.0%",
            "surprise_note_fa": "داده‌های تورم توکیو شاخص پیشرو برای سیاست بانک مرکزی ژاپن و روند USD/JPY است.",
            "source_name": "Bank of Japan (BoJ)",
            "source_url": "https://www.boj.or.jp/en/",
        },
        {
            "event_key": "au_employment_change",
            "event_name_en": "Australia Employment Change",
            "event_name_fa": "تغییرات اشتغال استرالیا",
            "country": "Australia",
            "currency": "AUD",
            "related_symbols": ["AUDUSD"],
            "category": "employment",
            "importance": "MEDIUM",
            "impact_pct": 74,
            "scheduled_at": now - timedelta(hours=5),
            "status": "PUBLISHED",
            "actual": "+31.4K",
            "forecast": "+24.0K",
            "previous": "+27.8K",
            "surprise_note_fa": "اشتغال بهتر از انتظار ثبت شد و به حمایت کوتاه‌مدت از دلار استرالیا کمک کرد.",
            "source_name": "Australian Bureau of Statistics (ABS)",
            "source_url": "https://www.abs.gov.au/",
        },
        {
            "event_key": "us_nfp_upcoming",
            "event_name_en": "US Nonfarm Payrolls (NFP)",
            "event_name_fa": "اشتغال بخش غیرکشاورزی آمریکا (NFP)",
            "country": "United States",
            "currency": "USD",
            "related_symbols": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"],
            "category": "employment",
            "importance": "HIGH",
            "impact_pct": 97,
            "scheduled_at": now + timedelta(days=1, hours=5),
            "status": "SCHEDULED",
            "actual": None,
            "forecast": "185K",
            "previous": "192K",
            "surprise_note_fa": "پرریسک‌ترین گزارش ماهانه فارکس و طلا؛ گارد خبری خودکار پیش از انتشار فعال می‌شود.",
            "source_name": "U.S. Bureau of Labor Statistics (BLS)",
            "source_url": "https://www.bls.gov/news.release/empsit.toc.htm",
        },
    ]

    for ev in sample_events:
        existing_ev = db.query(EconomicEvent).filter(EconomicEvent.event_key == ev["event_key"]).first()
        if existing_ev:
            continue
        db.add(
            EconomicEvent(
                event_key=ev["event_key"],
                event_name_en=ev["event_name_en"],
                event_name_fa=ev["event_name_fa"],
                country=ev["country"],
                currency=ev["currency"],
                related_symbols_json=json.dumps(ev["related_symbols"]),
                category=ev["category"],
                importance=ev["importance"],
                impact_pct=ev["impact_pct"],
                scheduled_at=ev["scheduled_at"],
                timezone_name="UTC",
                status=ev["status"],
                actual=ev["actual"],
                forecast=ev["forecast"],
                previous=ev["previous"],
                surprise_note_fa=ev["surprise_note_fa"],
                source_name=ev["source_name"],
                source_url=ev["source_url"],
                is_demo_data=True,
            )
        )

    db.commit()
    return created_items


def fetch_and_ingest_news(db: Session) -> List[NewsItem]:
    """
    Fetches multi-source financial RSS & official central bank feeds safely (SSRF-guarded,
    HTML-sanitized, deduplicated), scores each item with 5 independent metrics + Market Impact %,
    translates to Persian, and falls back to clearly labelled DEMO feed only when offline.
    """
    settings = get_settings()
    active_symbols = _get_active_trade_symbols(db)
    new_items: List[NewsItem] = []
    seen_hashes_in_batch: set[str] = set()
    live_sources_ok = 0

    if settings.nexvora_data_mode in ("live", "auto"):
        for src in NEWS_SOURCES:
            if not validate_external_url(src["url"], ALLOWED_NEWS_HOSTS):
                continue
            t0 = time.monotonic()
            try:
                with httpx.Client(
                    timeout=8.0,
                    follow_redirects=False,
                    headers={"User-Agent": "NEXVORA-NewsIntelligence/1.0"},
                ) as client:
                    resp = client.get(src["url"])
                    latency = int((time.monotonic() - t0) * 1000)
                    if resp.status_code != 200 or len(resp.content) > 2_000_000:
                        _record_news_health(db, src["key"], src["name"], "DEGRADED", latency, f"HTTP {resp.status_code}")
                        continue
                    feed = feedparser.parse(resp.content)
                    entries = feed.entries[:10]
                    if not entries:
                        _record_news_health(db, src["key"], src["name"], "DEGRADED", latency, "Empty feed")
                        continue
                    live_sources_ok += 1
                    _record_news_health(db, src["key"], src["name"], "HEALTHY", latency)

                    for entry in entries:
                        raw_title = sanitize_text(getattr(entry, "title", "") or "")
                        raw_summary = sanitize_text(getattr(entry, "summary", "") or "")
                        raw_link = (getattr(entry, "link", "") or src["url"]).strip()
                        if not raw_title or not validate_external_url(raw_link):
                            continue

                        pub_dt = utcnow()
                        pub_raw = getattr(entry, "published", None) or getattr(entry, "updated", None)
                        if pub_raw:
                            try:
                                pub_dt = parsedate_to_datetime(pub_raw)
                                if pub_dt.tzinfo is None:
                                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                            except Exception:
                                pub_dt = utcnow()

                        # Deduplicate by normalized headline + publication date so recurring official
                        # titles (e.g. "Federal Reserve issues FOMC statement" across months) don't collide,
                        # while identical entries within the same feed/batch are skipped cleanly.
                        dh = _dedupe_hash(raw_title, pub_dt.strftime("%Y-%m-%d"))
                        if dh in seen_hashes_in_batch:
                            continue
                        seen_hashes_in_batch.add(dh)
                        if db.query(NewsItem).filter(NewsItem.dedupe_hash == dh).first():
                            continue

                        scores = score_news_item(raw_title, raw_summary, src["type"], active_symbols)
                        fa_title, fa_summary = _translate_with_optional_llm(
                            raw_title, raw_summary, scores["category"], scores["related_currencies"]
                        )
                        item = NewsItem(
                            dedupe_hash=dh,
                            source_name=src["name"],
                            source_type=src["type"],
                            canonical_url=raw_link[:500],
                            original_headline=raw_title[:400],
                            persian_title=fa_title,
                            persian_summary=fa_summary,
                            summary_is_ai=True,
                            category=scores["category"],
                            related_currencies_json=json.dumps(scores["related_currencies"]),
                            related_symbols_json=json.dumps(scores["related_symbols"]),
                            impact_level=scores["impact_level"],
                            market_impact_pct=scores["market_impact_pct"],
                            importance_score=scores["importance_score"],
                            volatility_score=scores["volatility_score"],
                            currency_relevance_score=scores["currency_relevance_score"],
                            direction_bias=scores["direction_bias"],
                            direction_confidence=scores["direction_confidence"],
                            active_trade_risk_score=scores["active_trade_risk_score"],
                            methodology_note_fa=scores["methodology_note_fa"],
                            published_at=pub_dt,
                            is_demo_data=False,
                        )
                        try:
                            with db.begin_nested():
                                db.add(item)
                                db.flush()
                            new_items.append(item)
                        except IntegrityError:
                            # Already inserted concurrently or duplicate in feed — safe savepoint rollback
                            continue
                    db.commit()
            except Exception as exc:
                db.rollback()
                latency = int((time.monotonic() - t0) * 1000)
                try:
                    _record_news_health(db, src["key"], src["name"], "OFFLINE", latency, str(exc))
                except Exception:
                    db.rollback()

    if live_sources_ok == 0 and settings.nexvora_data_mode in ("demo", "auto"):
        _record_news_health(
            db,
            "demo_news_feed",
            "Sample News & Calendar (Offline Demo Mode)",
            "DEMO_FALLBACK",
            latency_ms=1,
        )
        new_items = _seed_labelled_demo_news_and_calendar(db, active_symbols)

    # Notify users on high-impact news with active trade risk
    if new_items:
        users = db.query(User).filter(User.is_active == True, User.notify_high_news == True).all()  # noqa: E712
        for n_item in new_items:
            if n_item.market_impact_pct >= 80 and n_item.active_trade_risk_score >= 70:
                for u in users:
                    exists = (
                        db.query(Notification)
                        .filter(Notification.user_id == u.id, Notification.related_news_id == n_item.id)
                        .first()
                    )
                    if not exists:
                        db.add(
                            Notification(
                                user_id=u.id,
                                kind="NEWS_RISK",
                                title_fa=f"هشدار خبر پرریسک ({n_item.market_impact_pct}% تاثیر)",
                                message_fa=f"{n_item.persian_title} — منبع: {n_item.source_name}",
                                severity="warning",
                                related_news_id=n_item.id,
                            )
                        )
        db.commit()

    return new_items


def is_news_blackout_for_symbol(db: Session, symbol: str, blackout_minutes: int = 30) -> bool:
    if blackout_minutes <= 0:
        return False
    now = utcnow()
    window_start = now - timedelta(minutes=blackout_minutes)
    window_end = now + timedelta(minutes=blackout_minutes)
    events = (
        db.query(EconomicEvent)
        .filter(
            EconomicEvent.importance == "HIGH",
            EconomicEvent.scheduled_at >= window_start,
            EconomicEvent.scheduled_at <= window_end,
        )
        .all()
    )
    for ev in events:
        syms = json.loads(ev.related_symbols_json or "[]")
        if symbol in syms:
            return True
    return False
