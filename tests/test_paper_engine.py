import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

from paper_engine import GAP_MAX, add_signals, equity_now, realised, step  # noqa: E402

RULES = [{"key": "paper_start", "value": 32000}, {"key": "risk_normal", "value": 1.0}, {"key": "risk_caution", "value": 0.5}]


class FakeProvider:
    def __init__(self, bars, vix=17.0, fx=88.0):
        self.bars, self._vix, self._fx = bars, vix, fx

    def daily(self, sym):
        return self.bars[sym]

    def vix(self, day):
        return self._vix

    def fx(self):
        return self._fx


def frame(rows, start="2026-11-02"):
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)


SIG = {"market": "NSE", "symbol": "ABC", "strategy": "breakout_52w", "signal_date": "2026-11-02", "signal_close": 100.0}


def run(bars, ledger=None, signals=(), today="2026-11-20", **kw):
    ledger, eq = step(ledger or [], [], RULES, list(signals), FakeProvider({"ABC.NS": bars}, **kw), today)
    return ledger, eq


def pending():
    ledger, _ = run(frame([[100, 101, 99, 100]]), signals=[SIG], today="2026-11-02")
    return ledger


def test_new_signal_becomes_pending_and_is_not_duplicated():
    ledger = pending()
    assert ledger[0]["status"] == "PENDING" and ledger[0]["stop"] == 95.0 and ledger[0]["target"] == 120.0
    again = add_signals(ledger, [SIG], RULES)
    assert len(again) == 1


def test_fill_then_target_hit_is_a_win_with_the_expected_r():
    bars = frame([[100, 101, 99, 100], [101, 103, 100, 102], [102, 125, 101, 124]])   # 3rd day trades through 121.2
    ledger, eq = step(pending(), [], RULES, [], FakeProvider({"ABC.NS": bars}), "2026-11-05")
    r = ledger[0]
    assert r["status"] == "WIN" and r["entry"] == 101.0 and r["target"] == 121.2
    # caution risk 0.5% of 32,000 = 160; per share risk 5.05; 31 shares; risk about 156.55
    assert r["qty"] == 31 and abs(r["risk_rs"] - 156.55) < 0.01
    assert r["r_mult"] > 3.5 and r["pnl_rs"] > 500
    assert eq[-1]["equity"] == round(32000 + r["pnl_rs"], 2)


def test_stop_is_assumed_first_when_a_bar_touches_both():
    bars = frame([[100, 101, 99, 100], [100, 125, 94, 110]])                      # touches target and stop on one bar
    ledger, _ = step(pending(), [], RULES, [], FakeProvider({"ABC.NS": bars}), "2026-11-05")
    assert ledger[0]["status"] == "LOSS" and ledger[0]["exit"] == ledger[0]["stop"]


def test_gap_over_three_percent_skips_the_trade():
    bars = frame([[100, 101, 99, 100], [105, 106, 104, 105]])                    # opens +5%
    ledger, _ = step(pending(), [], RULES, [], FakeProvider({"ABC.NS": bars}), "2026-11-05")
    assert ledger[0]["status"] == "SKIPPED" and realised(ledger) == 0 and GAP_MAX == 0.03


def test_open_trade_is_marked_to_market_in_equity():
    bars = frame([[100, 101, 99, 100], [100, 104, 99, 103], [103, 106, 102, 105]])
    ledger, eq = step(pending(), [], RULES, [], FakeProvider({"ABC.NS": bars}), "2026-11-05")
    assert ledger[0]["status"] == "OPEN" and ledger[0]["unrealized_rs"] > 0
    assert eq[-1]["equity"] == round(equity_now(ledger, RULES), 2) > 32000


def test_time_stop_after_forty_sessions():
    rows = [[100, 101, 99, 100]] + [[100, 105, 99, 102]] * 42
    bars = frame(rows)
    ledger, _ = step(pending(), [], RULES, [], FakeProvider({"ABC.NS": bars}), "2027-01-20")
    assert ledger[0]["status"] in ("TIME STOP",) and ledger[0]["closed"] != ""


def test_crypto_exits_on_a_close_below_the_prior_ten_day_low():
    up = [[100 + i, 101 + i, 99 + i, 100 + i] for i in range(25)]
    drop = [[125, 126, 90, 92], [92, 93, 85, 86]]                                # closes under the 10-day low
    idx = pd.bdate_range("2026-10-01", periods=len(up) + len(drop))
    bars = pd.DataFrame(up + drop, columns=["Open", "High", "Low", "Close"], index=idx)
    sig = {"market": "CRYPTO", "symbol": "BTC-USD", "strategy": "donchian_20_10", "signal_date": str(idx[22].date()), "signal_close": 122.0, "atr": 2.0}
    prov = FakeProvider({"BTC-USD": bars})
    ledger, _ = step([], [], RULES, [sig], prov, str(idx[22].date()))
    ledger, _ = step(ledger, [], RULES, [], prov, str(idx[-1].date()))
    r = ledger[0]
    assert r["status"] in ("WIN", "LOSS") and r["qty"] > 0 and r["target"] == ""


def test_filing_reaction_is_measured_from_the_minute_bars():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dashboard.make_alerts import reaction, read_of
    idx = pd.date_range("2026-11-11 09:15", periods=60, freq="min", tz="Asia/Kolkata")
    close = [100 + (i - 30) * 0.2 if i > 30 else 100 for i in range(60)]
    m = pd.DataFrame({"Open": close, "High": [c * 1.002 for c in close], "Low": close, "Close": close}, index=idx)
    r = reaction(m, 100.0, idx[30].to_pydatetime())
    assert r["at_filing"] == 0.0 and r["since_filing"] > 5 and r["day_pct"] > 5
    assert read_of(r) == "Rose after the filing"
    assert read_of({"at_filing": 9.5, "since_filing": 1.0}) == "Moved before the filing"
