from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES, SYMBOL_META, TIMEFRAME_META
from app.database import get_db
from app.engine.backtester import build_params_for_timeframe
from app.engine.market_data import get_market_series
from app.engine.scheduler import get_or_create_engine_config
from app.engine.trading_hub3 import REJECTION_LABELS_FA, run_trading_hub3_engine
from app.models import BacktestQualification, User
from app.security import get_current_user

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/overview")
def get_market_overview(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = get_or_create_engine_config(db)
    quals = {
        (q.symbol, q.timeframe): q
        for q in db.query(BacktestQualification).all()
    }

    instruments: List[dict] = []
    cur_changes: Dict[str, List[float]] = defaultdict(list)

    for sym in ALLOWED_SYMBOLS:
        meta = SYMBOL_META[sym]
        s15 = get_market_series(sym, "15m", limit=180, db=db)
        last_c = s15.candles[-1]
        prev_c = s15.candles[-24] if len(s15.candles) >= 24 else s15.candles[0]
        chg_pct = round(((last_c.close - prev_c.close) / prev_c.close) * 100.0, 2) if prev_c.close else 0.0

        cur_changes[meta["base"]].append(chg_pct)
        cur_changes[meta["quote"]].append(-chg_pct)

        tf_states = []
        for tf in ALLOWED_TIMEFRAMES:
            s_tf = s15 if tf == "15m" else get_market_series(sym, tf, limit=260, db=db)
            ev = run_trading_hub3_engine(sym, tf, s_tf.candles, params=build_params_for_timeframe(cfg, tf))
            q = quals.get((sym, tf))
            tf_states.append({
                "timeframe": tf,
                "label_fa": TIMEFRAME_META[tf]["label_fa"],
                "risk_tier": TIMEFRAME_META[tf]["risk_tier"],
                "state": ev.state,
                "htf_bias": ev.htf_bias,
                "adx": ev.adx_value,
                "readiness_pct": ev.readiness_pct,
                "why_no_trade_fa": ev.why_no_trade_fa,
                "eligible_for_telegram": bool(q.eligible_for_telegram) if q else False,
                "backtest_win_rate": float(q.win_rate) if q else 0.0,
                "backtest_profit_factor": float(q.profit_factor) if q else 0.0,
                "backtest_trades": int(q.total_trades) if q else 0,
                "is_demo_data": series.is_demo_data,
                "di_plus": ev.di_plus,
                "di_minus": ev.di_minus,
                "min_score": ev.policy.min_score if ev.policy else 0.0,
                "min_adx": ev.policy.min_adx if ev.policy else 0.0,
                "rejections": ev.rejection_counts,
                "rejections_fa": {k: REJECTION_LABELS_FA.get(k, k) for k in ev.rejection_counts},
            })

        instruments.append({
            "symbol": sym,
            "display": meta["display"],
            "name_fa": meta["name_fa"],
            "market_class": meta["market_class"],
            "digits": meta["digits"],
            "price": last_c.close,
            "high_recent": max(c.high for c in s15.candles[-24:]),
            "low_recent": min(c.low for c in s15.candles[-24:]),
            "change_pct": chg_pct,
            "source": s15.source,
            "is_demo_data": s15.is_demo_data,
            "updated_at": s15.fetched_at,
            "timeframes": tf_states,
        })

    # Documented Currency Strength derived solely from the 6 tracked instruments
    strength = []
    for cur in ("USD", "EUR", "GBP", "JPY", "AUD", "XAU"):
        vals = cur_changes.get(cur, [])
        avg = sum(vals) / len(vals) if vals else 0.0
        # Normalize roughly around 50 (range 0..100)
        score = int(max(5, min(95, round(50 + avg * 35))))
        strength.append({
            "currency": cur,
            "strength_score": score,
            "avg_change_pct": round(avg, 3),
            "pairs_count": len(vals),
        })
    strength.sort(key=lambda x: x["strength_score"], reverse=True)

    return {
        "allowed_symbols": ALLOWED_SYMBOLS,
        "allowed_timeframes": ALLOWED_TIMEFRAMES,
        "strength_methodology_fa": "قدرت نسبی ارزها صرفاً از میانگین تغییرات ۲۴ کندل اخیر همین ۶ نماد مجاز محاسبه شده است.",
        "instruments": instruments,
        "currency_strength": strength,
    }


@router.get("/candles")
def get_candles(
    symbol: str = Query(default="EURUSD"),
    timeframe: str = Query(default="15m"),
    limit: int = Query(default=160, ge=30, le=350),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if symbol not in ALLOWED_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"نماد نامعتبر است. فقط ۶ نماد مجاز: {', '.join(ALLOWED_SYMBOLS)}")
    if timeframe not in ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"تایم‌فریم نامعتبر است. فقط: {', '.join(ALLOWED_TIMEFRAMES)}")

    series = get_market_series(symbol, timeframe, limit=limit, db=db)
    return {
        "symbol": symbol,
        "display": SYMBOL_META[symbol]["display"],
        "timeframe": timeframe,
        "timeframe_label_fa": TIMEFRAME_META[timeframe]["label_fa"],
        "risk_tier": TIMEFRAME_META[timeframe]["risk_tier"],
        "digits": SYMBOL_META[symbol]["digits"],
        "source": series.source,
        "is_demo_data": series.is_demo_data,
        "fetched_at": series.fetched_at,
        "candles": [
            {
                "time": int(c.timestamp.timestamp()),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in series.candles
        ],
    }
