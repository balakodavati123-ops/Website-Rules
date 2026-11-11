import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backtest"))

from spike_study import classify, find_spikes, prep, window  # noqa: E402
from trading_team.spike_watch import IST, trigger_of, verdict  # noqa: E402


def item(desc, text):
    return {"symbol": "X", "desc": desc, "text": text, "file": "",
            "time": datetime(2026, 11, 11, 10, 0, tzinfo=IST)}


def test_trigger_types():
    assert trigger_of(item("Outcome of Board Meeting", "submitted the financial results for the quarter")) == "RESULTS"
    assert trigger_of(item("General Updates", "Receipt of Letter of Award for a metro project")) == "ORDER/CONTRACT"
    assert trigger_of(item("Copy of Newspaper Publication", "financial results published")) is None
    assert trigger_of(item("General Updates", "Change in registered office")) is None


def test_verdict_flags_moves_that_came_before_the_filing():
    snap = {"at_filing_pct": 9.5, "since_filing_pct": 0.9, "day_pct": 10.5}
    assert verdict("ORDER/CONTRACT", snap).startswith("MOVED BEFORE THE FILING")
    fresh = {"at_filing_pct": 0.2, "since_filing_pct": 0.3, "day_pct": 0.5}
    assert verdict("RESULTS", fresh).startswith("NOT MOVING YET")
    late = {"at_filing_pct": 1.0, "since_filing_pct": 16.0, "day_pct": 17.0}
    assert verdict("RESULTS", late).startswith("LATE")


def test_classify_priority_and_noise():
    rows = lambda d, t: [{"desc": d, "text": t, "time": pd.Timestamp("2026-01-01")}]
    assert classify([]) == "no announcement"
    assert classify(rows("Outcome of Board Meeting", "the financial results for the quarter")) == "results"
    assert classify(rows("General Updates", "bagged a work order worth 500 crore")) == "order / contract win"
    assert classify(rows("Copy of Newspaper Publication", "notice")) == "routine filing only"
    assert classify(rows("Updates", "change of auditor")) == "other announcement"


def test_window_uses_previous_close_to_close():
    day, prev = pd.Timestamp("2026-11-11"), pd.Timestamp("2026-11-10")
    rows = [{"time": pd.Timestamp("2026-11-10 15:00")},   # before the previous close: excluded
            {"time": pd.Timestamp("2026-11-10 18:00")},   # evening before: included
            {"time": pd.Timestamp("2026-11-11 10:00")},   # during the session: included
            {"time": pd.Timestamp("2026-11-11 16:00")}]   # after the close: excluded
    assert len(window(rows, day, prev)) == 2


def test_find_spikes_requires_volume_liquidity_and_sane_jump():
    idx = pd.bdate_range("2026-01-01", periods=60)
    base = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0,
                         "Volume": 1_000_000.0}, index=idx)
    ok = base.copy()
    ok.iloc[40, ok.columns.get_loc("High")] = 115.0
    ok.iloc[40, ok.columns.get_loc("Volume")] = 5_000_000.0
    thin = ok.copy()
    thin["Volume"] = thin["Volume"] / 1000          # turnover far below Rs 2 crore
    quiet = base.copy()
    quiet.iloc[40, quiet.columns.get_loc("High")] = 115.0   # jump on ordinary volume
    absurd = ok.copy()
    absurd.iloc[40, absurd.columns.get_loc("High")] = 400.0  # split artefact
    got = find_spikes({"OK": ok, "THIN": thin, "QUIET": quiet, "ABSURD": absurd})
    assert list(got.symbol) == ["OK"]
