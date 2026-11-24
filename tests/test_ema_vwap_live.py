import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "quant"))
import desks as D                                  # noqa: E402
import ema_vwap_live as EV                         # noqa: E402
from src.research import ema_vwap as BT            # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def _day(path):
    """{HH:MM: (o, h, l, c, v)} for 09:15-15:29 from a price function of the minute index."""
    out = {}
    for i in range(375):
        t = (datetime(2026, 11, 24, 9, 15) + timedelta(minutes=i)).strftime("%H:%M")
        px = path(i)
        out[t] = (px, px + 1.0, px - 1.0, px, 100.0 + i % 7)
    return out


def _vee(i):                     # falls 150 points to 10:30, rallies 300 to 12:00, then drops hard
    if i < 75:
        return 25000 - 2 * i
    if i < 165:
        return 24850 + (i - 75) * 300 / 90
    return 25150 - (i - 165) * 4


def test_live_indicators_match_the_backtest_exactly():
    d0, d1 = date(2026, 11, 23), date(2026, 11, 24)
    prev, today = _day(lambda i: 25000 + (i % 30) - 15), _day(_vee)
    bt = BT.indicators({d0: prev, d1: today}, [d0, d1])
    ema0 = EV.indicators(EV.three_minute(prev), None)[-1][6]
    live = EV.indicators(EV.three_minute(today), ema0)
    assert len(live) == len(bt[d1]) == 125
    for a, b in zip(live, bt[d1]):
        assert a[:6] == b[:6] and abs(a[6] - b[6]) < 1e-9 and abs(a[7] - b[7]) < 1e-9
    assert EV.three_minute(today, upto="10:02")[-1][1] == "10:00"                     # the 10:00-10:03 candle is not complete at 10:02


def test_filters_skip_whipsaws_and_flat_vwap():
    rows = [("", f"10:{m:02d}", 0, 0, 0, 0, e, v) for m, e, v in
            [(0, 99, 100), (3, 101, 100.5), (6, 99, 100.6), (9, 101, 100.7), (12, 102, 100.9)]]
    s = EV.signals(rows, slope_bars=0, cooldown_min=30)
    assert [x["take"] for x in s] == [True, False, False, False]                       # the crossovers at 10:06 and 10:09 come within 30 minutes
    assert "after the last crossover" in s[1]["why"]
    down = [("", "10:00", 0, 0, 0, 0, 99, 100), ("", "10:03", 0, 0, 0, 0, 99.5, 101), ("", "10:06", 0, 0, 0, 0, 99.8, 101.5), ("", "10:09", 0, 0, 0, 0, 102, 101.8)]
    s = EV.signals(down, slope_bars=3, cooldown_min=0)
    assert s[-1]["up"] and s[-1]["take"]                                                # VWAP rose over 3 candles with the upward cross
    flat = down[:3] + [("", "10:09", 0, 0, 0, 0, 102, 99.0)]
    s = EV.signals([r[:6] + (r[6], 100.0 + (0.5 if i == 0 else 1.0 if i == 1 else 1.5)) for i, r in enumerate(down[:3])] + [("", "10:09", 0, 0, 0, 0, 102, 99.5)], slope_bars=3)
    assert s[-1]["up"] and not s[-1]["take"] and "against the crossover" in s[-1]["why"]


def _chain(spot):
    rows = []
    for k in range(24700, 25351, 50):
        ce, pe = max(5.0, 120 + (spot - k) * 0.5), max(5.0, 120 - (spot - k) * 0.5)
        rows.append({"strike_price": float(k), "call_options": {"instrument_key": f"CE{k}", "market_data": {"bid_price": ce - 0.5, "ask_price": ce + 0.5, "volume": 10}},
                     "put_options": {"instrument_key": f"PE{k}", "market_data": {"bid_price": pe - 0.5, "ask_price": pe + 0.5, "volume": 10}}})
    return rows


def test_a_session_on_paper_books_a_call_and_exits_on_the_ema_breach():
    prev, today = _day(lambda i: 25000 + (i % 30) - 15), _day(_vee)
    ema0 = EV.indicators(EV.three_minute(prev), None)[-1][6]
    book, room, opened, view = D.new_book(), [100000.0], [], {}
    for i in range(6, 375):
        now = datetime(2026, 11, 24, 9, 15, 20, tzinfo=IST) + timedelta(minutes=i)
        hh = now.strftime("%H:%M")
        bars1 = [[t, *v] for t, v in sorted(today.items()) if t < hh]                   # candles up to the minute that has finished
        spot = today[bars1[-1][0]][3]
        view = EV.step(book, now, {"bars1": bars1, "ema0": ema0, "chains": {"2026-11-24": _chain(spot)}, "expiry": "2026-11-24", "lot": 65, "spot": spot, "room": room, "fut": "NIFTY FUT"}, set())
        opened += [t["id"] for t in book["trades"] if t["id"] not in opened]
    tr = [t for t in book["trades"] if t["strategy"] == EV.STRATEGY]
    assert [(t["legs"][0]["kind"], t["opened"][:5]) for t in tr] == [("CE", "09:21"), ("CE", "11:03"), ("PE", "12:54")]
    assert [x["taken"] for x in view["crosses"]] == [True, False, True, True] and "30" in view["crosses"][1]["why"]   # 09:33 came 12 minutes after 09:21
    c = tr[1]                                                                            # the call bought in the rally
    assert c["status"] == "WIN" and c["horizon"] == "daily" and c["margin_rs"] == round(c["legs"][0]["entry"] * 65)
    assert c["why"].startswith("EMA9 breach: the 12:12") and tr[2]["why"].startswith("time: square-off")
    x = c["exit_premium"]
    assert abs(c["pnl_rs"] - ((x - c["legs"][0]["entry"]) * 65 - EV.charges(c["legs"][0]["entry"] * 65, x * 65))) < 0.01
    assert all(t["status"] != "OPEN" for t in tr)                                       # flat by 15:20
    # the straddle desk's loop leaves this book alone
    t0 = dict(c, status="OPEN", pnl_rs=1.0)
    book2 = {"trades": [t0], "seen": {}, "seq": 0}
    D.fno_step(book2, datetime(2026, 11, 24, 15, 25, tzinfo=IST), {"chains": {"2026-11-24": _chain(25000)}, "expiry": "2026-11-24", "lot": 65}, set())
    assert t0["status"] == "OPEN" and t0["pnl_rs"] == 1.0


def test_charges_match_the_backtest_costs():
    from src.backtest.costs import charges
    assert abs(EV.charges(7800, 9100) - charges(7800, 9100, orders=2)["total"]) < 0.05


def test_record_keeps_the_two_books_apart():
    tt = [{"desk": "FNO", "strategy": EV.STRATEGY, "status": "WIN", "pnl_rs": 500, "day": "2026-11-24", "opened": "10:03:20", "id": "a"},
          {"desk": "FNO", "strategy": EV.STRATEGY, "status": "LOSS", "pnl_rs": -300, "day": "2026-11-24", "opened": "11:03:20", "id": "b"},
          {"desk": "FNO", "strategy": "long_straddle", "status": "LOSS", "pnl_rs": -900, "day": "2026-11-24", "opened": "10:00:10", "id": "c"}]
    e, s = EV.record(tt, EV.STRATEGY), EV.record(tt, "long_straddle")
    assert (e["closed"], e["wins"], e["total_rs"], e["avg_rs"]) == (2, 1, 200, 100) and (s["closed"], s["total_rs"]) == (1, -900)


def _run_on_quotes(start_min, today, ema0, atp_before=None):
    """Drive the desk with live quotes every 15 seconds and no Upstox candles, as on 24 Nov 2026."""
    book, room, view, cum = D.new_book(), [100000.0], {}, 0.0
    for j in range(start_min * 4, 375 * 4):
        now = datetime(2026, 11, 24, 9, 15, 5, tzinfo=IST) + timedelta(seconds=15 * j)
        bar = today[now.strftime("%H:%M")] if now.strftime("%H:%M") in today else None
        if bar is None:
            break
        cum += 25.0
        atp = atp_before if atp_before is not None else bar[3]
        EV.tick(book, now, {"last_price": bar[3], "volume": 1_000_000 + cum, "average_price": atp})
        view = EV.step(book, now, {"bars1": [], "ema0": ema0, "chains": {"2026-11-24": _chain(bar[3])}, "expiry": "2026-11-24", "lot": 65, "spot": bar[3], "room": room, "fut": "NIFTY FUT"}, set())
    return book, view


def test_quote_built_bars_trade_the_same_session_when_upstox_serves_no_candles():
    prev, today = _day(lambda i: 25000 + (i % 30) - 15), _day(_vee)
    ema0 = EV.indicators(EV.three_minute(prev), None)[-1][6]
    book, view = _run_on_quotes(0, today, ema0)
    tr = [t for t in book["trades"] if t["strategy"] == EV.STRATEGY]
    assert view["source"].startswith("1-minute bars built from live quotes") and view["seeded"] and view["warmup"] is None
    assert ("CE", "11:03") in [(t["legs"][0]["kind"], t["opened"][:5]) for t in tr] and ("PE", "12:54") in [(t["legs"][0]["kind"], t["opened"][:5]) for t in tr]
    assert all(t["status"] != "OPEN" for t in tr)


def test_mid_session_start_anchors_vwap_on_the_session_and_warms_up_the_ema():
    prev, today = _day(lambda i: 25000 + (i % 30) - 15), _day(_vee)
    ema0 = EV.indicators(EV.three_minute(prev), None)[-1][6]
    book, view = _run_on_quotes(105, today, ema0, atp_before=24900.0)            # engine restarted at 11:00
    st = book["ema_vwap_state"]
    assert st["vw0"][:2] == [24900.0 * 1_000_025.0, 1_000_025.0] and view["warmup"]["needed"] == EV.WARMUP and view["warmup"]["from"] == "11:00"
    assert abs(view["last"][0]["vwap"] - 24900.0) < 5.0                          # the session's earlier trading (1M units) dominates the VWAP
    tr = [t for t in book["trades"] if t["strategy"] == EV.STRATEGY]
    assert all(t["opened"][:5] >= "11:36" for t in tr)                             # nothing before 12 candles of warm-up
    assert any("warming up" in c["why"] for c in view["crosses"]) or not [c for c in view["crosses"] if c["end"] < "11:36"]
