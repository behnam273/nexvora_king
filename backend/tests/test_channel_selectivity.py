"""
The Telegram channel targets a >70% win rate. Publishing every symbol/timeframe
cell makes that arithmetically impossible, so the channel must be selective and
the selection must be driven by evidence, not by cherry-picking trades.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import backtester  # noqa: E402


class _Q:
    def __init__(self, sym, tf, wr, pf, n, exp, demo=False, eligible=True):
        self.symbol = sym
        self.timeframe = tf
        self.win_rate = wr
        self.profit_factor = pf
        self.total_trades = n
        self.expectancy_r = exp
        self.eligible_for_telegram = eligible
        self.is_demo_data = demo
        self.reason_fa = ""
        self.channel_rank = 0


class _DB:
    def commit(self):
        pass


def _run(rows):
    backtester._apply_channel_selectivity(_DB(), rows)
    return rows


def test_only_cells_above_target_are_published_and_capped():
    rows = [
        _Q("EURUSD", "4H", 78.0, 2.4, 40, 0.55),   # strong
        _Q("XAUUSD", "4H", 74.0, 2.0, 25, 0.42),   # strong
        _Q("GBPUSD", "15m", 71.0, 1.8, 18, 0.30),  # just above target
        _Q("USDJPY", "4H", 72.0, 1.7, 22, 0.28),   # above target
        _Q("AUDUSD", "4H", 72.0, 1.6, 21, 0.25),   # above target but lowest score
        _Q("EURGBP", "4H", 61.0, 1.4, 30, 0.10),   # below target
        _Q("EURUSD", "5m", 90.0, 9.99, 3, 1.80),   # tiny sample: must not qualify
        _Q("EURUSD", "15m", 95.0, 9.99, 60, 1.50, demo=True),  # demo: never published
    ]
    _run(rows)
    published = [r for r in rows if r.eligible_for_telegram]

    assert len(published) <= backtester.CHANNEL_MAX_CELLS
    assert all(r.win_rate >= backtester.CHANNEL_TARGET_WINRATE for r in published)
    assert all(r.total_trades >= backtester.CHANNEL_MIN_CELL_TRADES for r in published)
    assert all(not r.is_demo_data for r in published)

    # the tiny-sample 90% cell and the demo 95% cell must be excluded
    assert not any(r.timeframe == "5m" for r in published)
    assert not any(r.is_demo_data for r in published)

    # ranks are 1..N and unique
    ranks = sorted(r.channel_rank for r in published)
    assert ranks == list(range(1, len(published) + 1))


def test_below_target_cell_carries_explanatory_reason():
    rows = [_Q("EURGBP", "4H", 61.0, 1.4, 30, 0.10), _Q("EURUSD", "4H", 80.0, 2.5, 40, 0.6)]
    _run(rows)
    weak = next(r for r in rows if r.symbol == "EURGBP")
    assert weak.eligible_for_telegram is False
    assert "70" in weak.reason_fa or "کانال" in weak.reason_fa


def test_empty_portfolio_does_not_crash():
    assert _run([]) == []
