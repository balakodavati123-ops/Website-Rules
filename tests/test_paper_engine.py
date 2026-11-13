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


def test_crypto_quote_is_verified_only_when_two_sources_agree():
    from datetime import datetime, timedelta, timezone
    from dashboard.make_crypto import candle_rows, quote_row
    now = datetime(2026, 11, 11, 20, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    tick = {"last_price": "7388337.5", "change_24_hour": "-0.53", "high": "7499900", "low": "7300001"}
    ok = quote_row("BTC", "Bitcoin", tick, 100.83, 73594.4, 93.9, [1, 2], now)        # 7388337/100.83 = 73,275: within 2%
    assert ok["verified"] == "yes" and ok["premium_pct"] == 6.9 and ok["price_inr"] == 7388337.5
    off = quote_row("BTC", "Bitcoin", tick, 100.83, 60000.0, 93.9, [], now)           # sources disagree by 22%
    assert off["verified"] == "single source"
    lone = quote_row("BTC", "Bitcoin", tick, 100.83, None, None, [], now)             # Kraken down
    assert lone["verified"] == "single source" and lone["price_usd"] is None and lone["premium_pct"] is None
    rows = candle_rows("BTC", "1d", [{"open": 2, "high": 3, "low": 1, "close": 2.5, "volume": 1, "time": 1794355200000},
                                     {"open": 1, "high": 2, "low": 0.5, "close": 2, "volume": 1, "time": 1794268800000},
                                     {"open": 0, "high": 2, "low": 0, "close": 1, "volume": 1, "time": 1794182400000}])
    assert [r["c"] for r in rows] == [2, 2.5] and rows[0]["t"] < rows[1]["t"]          # oldest first, bad bar dropped


def test_floor_rules_on_indmoney_shaped_rows():
    """The floor's 8 rules, score and paper sizing are JavaScript; this runs their own check when node is installed."""
    import shutil
    import subprocess
    import pytest
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = Path(__file__).resolve().parents[1] / "dashboard" / "test" / "floor_calc_test.js"
    out = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-800:]


def test_fo_engine_books_and_settles_defined_risk_structures(tmp_path, monkeypatch):
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import dashboard.fo_engine as fo
    importlib.reload(fo)
    monkeypatch.setattr(fo, "LEDGER", tmp_path / "fo_ledger.json")
    ch = {24850: (47.3, 47.45, -0.22), 24700: (22.95, 23.05, -0.12), 24950: (73.6, 73.8, -0.31), 24800: (37.3, 37.45, -0.18),
          25100: (159.0, 159.4, 0.53), 25250: (94.05, 94.25, 0.37), 25400: (52.5, 52.65, 0.24), 25550: (28.6, 28.7, 0.14)}
    rows = [{"strike_price": k, "call_data": {"buy_price": b, "sell_price": a, "delta": abs(d), "lot_size": 65},
             "put_data": {"buy_price": b, "sell_price": a, "delta": -abs(d), "lot_size": 65}} for k, (b, a, d) in ch.items()]
    q, strikes, spot, exp, lot = fo.quotes({"selected_expiry": "20261117", "entity_details": {"live_price": 25110.95}, "option_chain_data": rows})
    assert lot == 65 and exp == "2026-11-17" and strikes[0] == 24700
    st = fo.structures(q, strikes, spot)
    assert st["short_iron_condor"] == [("S", 25400, "CE"), ("B", 25550, "CE"), ("S", 24850, "PE"), ("B", 24700, "PE")]
    assert st["bull_put_spread"] == [("S", 24950, "PE"), ("B", 24800, "PE")]
    # settle a condor at an inside close (full win) and an iron fly through the wing (full loss)
    fo.save([
        {"id": 1, "strategy": "short_iron_condor", "underlying": "NIFTY", "expiry": "2026-11-17", "lot": 65, "booked": "2026-11-13",
         "status": "OPEN", "legs": [{"side": "S", "strike": 25400, "kind": "CE", "entry": 52.5}, {"side": "B", "strike": 25550, "kind": "CE", "entry": 28.7},
                                    {"side": "S", "strike": 24850, "kind": "PE", "entry": 47.3}, {"side": "B", "strike": 24700, "kind": "PE", "entry": 23.05}],
         "credit_rs": 3123.25, "max_gain_rs": 2923.25, "max_loss_rs": 6826.75, "settle_close": "", "pnl_rs": 0, "note": ""},
        {"id": 2, "strategy": "iron_butterfly", "underlying": "NIFTY", "expiry": "2026-11-17", "lot": 65, "booked": "2026-11-13",
         "status": "OPEN", "legs": [{"side": "S", "strike": 25100, "kind": "CE", "entry": 159.0}, {"side": "B", "strike": 25250, "kind": "CE", "entry": 94.25},
                                    {"side": "S", "strike": 25100, "kind": "PE", "entry": 132.6}, {"side": "B", "strike": 24950, "kind": "PE", "entry": 73.8}],
         "credit_rs": 8030.75, "max_gain_rs": 7830.75, "max_loss_rs": 1919.25, "settle_close": "", "pnl_rs": 0, "note": ""}])

    class FakeT:
        def __init__(self, *a, **k): pass
        def history(self, **k):
            idx = pd.to_datetime(["2026-11-17"]).tz_localize("Asia/Kolkata")
            return pd.DataFrame({"Close": [25350.0]}, index=idx)
    monkeypatch.setattr(fo, "datetime", __import__("dashboard.fo_engine", fromlist=["datetime"]).datetime)
    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", FakeT)
    import dashboard.fo_engine as fo2
    fake_now = fo.datetime(2026, 11, 18, 9, 0, tzinfo=fo.IST)

    class FakeDT(fo.datetime):
        @classmethod
        def now(cls, tz=None): return fake_now
    monkeypatch.setattr(fo, "datetime", FakeDT)
    fo.settle()
    out = {r["id"]: r for r in fo.load()}
    assert out[1]["status"] == "WIN" and out[1]["pnl_rs"] == 3123.25 - 200          # inside the band: keep the credit
    assert out[2]["status"] == "LOSS" and out[2]["pnl_rs"] == round((123.55 - 150) * 65 - 200, 2)
