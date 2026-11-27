"""The live macro read (backend/macro.py): factor moves since NIFTY's close, the implied move, the live call and its measured hit rate,
stale feeds, headline themes, alerts and the F&O view built on it. No network: synthetic prices."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import fno_view as FV     # noqa: E402
import macro as M         # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
MODEL = {"days": 888, "from": "2022-01-04", "to": "2026-11-25",
         "same_day": {"r2": 0.2, "intercept": 0.02, "factors": {"usdinr": {"beta": -0.35}, "brent": {"beta": -0.014}, "dxy": {"beta": -0.17},
                                                                "spx_overnight": {"beta": 0.16}, "n225": {"beta": 0.14}, "hsi": {"beta": 0.095}},
                      "sensex_betas": {"usdinr": -0.36, "brent": -0.015, "dxy": -0.18, "spx_overnight": 0.17, "n225": 0.15, "hsi": 0.1}},
         "shocks": {"usdinr": {"threshold_pct": 0.35, "up": {"days": 91, "nifty_avg_pct": -0.23, "nifty_fell_pct": 54.9}, "down": {"days": 72, "nifty_avg_pct": 0.49, "nifty_fell_pct": 38.9}},
                    "brent": {"threshold_pct": 2.0, "up": {"days": 155, "nifty_avg_pct": -0.1, "nifty_fell_pct": 54.2}, "down": {"days": 135, "nifty_avg_pct": -0.02, "nifty_fell_pct": 57.8}}},
         "usdinr_record": {"value": 96.9, "day": "2026-07-23"},
         "pre_open": {"intercept": 0.02, "factors": {"spx_lastnight": 0.19, "ndx_lastnight": 0.03, "vix_lastnight": -0.007, "brent_yday": -0.005, "usdinr_yday": -0.015,
                                                     "dxy_yday": -0.13, "us10y_yday": 0.017},
                      "test": {"days": 338, "close_to_close_hit": 54.7, "open_to_close_hit": 47.0, "strong_days": 75, "strong_close_to_close_hit": 61.3}}}
INTR = {c: {"days": 481, "agree_days": 150, "agree_hit": h, "disagree_days": 33, "disagree_macro_hit": 51.5, "macro_strong_days": 200, "macro_strong_hit": 55.0,
            "momentum_hit": 54.0} for c, h in (("10:15", 50.0), ("11:15", 56.4), ("12:15", 58.4), ("13:15", 56.0))}


def ts(d, hm):
    return datetime.fromisoformat(f"{d}T{hm}:00+05:30").timestamp()


def series(ref, last, last_at=("2026-11-27", "12:00"), day0="2026-11-26"):
    """Bars every 15 minutes from 09:15 the day before to last_at: flat at `ref`, then `last` after 09:15 today."""
    out, t, end = [], ts(day0, "09:15"), ts(*last_at)
    while t <= end:
        out.append((int(t), ref if t < ts("2026-11-27", "09:15") else last))
        t += 900
    return {"bars": out, "gmtoffset": 0}


def world(**chg):
    base = {"usdinr": 90.0, "brent": 90.0, "dxy": 100.0, "es": 6000.0, "n225": 50000.0, "hsi": 20000.0, "nifty": 25000.0, "sensex": 82000.0}
    s = {k: series(v, v * (1 + chg.get(k, 0.0) / 100)) for k, v in base.items()}
    return {"at": ts("2026-11-27", "12:00"), "series": s}


def india(nifty_chg=-1.0):
    return {"day": "2026-11-27", "nifty": {"last": 25000 * (1 + nifty_chg / 100), "prev": 25000.0}, "sensex": {"last": 82000 * (1 + nifty_chg / 100), "prev": 82000.0},
            "vix": {"last": 16.5, "prev": 15.0}, "qs": {"HDFCBANK": [1900, -2.0], "ICICIBANK": [1300, -1.5], "RELIANCE": [1400, 0.5], "TCS": [3500, 1.2], "INFY": [1500, 1.0],
                                                         "BPCL": [300, -3.0], "HINDPETRO": [380, -3.4], "IOC": [140, -2.6]}}


NOW = datetime(2026, 11, 27, 12, 20, tzinfo=IST)


def test_ref_close_is_the_last_finished_session():
    bars = series(1, 1)["bars"]
    d, t = M.ref_close(NOW, bars)
    assert str(d) == "2026-11-26" and t == ts("2026-11-26", "15:30")
    d, _ = M.ref_close(datetime(2026, 11, 27, 16, 0, tzinfo=IST), bars)
    assert str(d) == "2026-11-27"
    d, _ = M.ref_close(datetime(2026, 11, 30, 8, 0, tzinfo=IST), None)          # Monday morning, no data: Friday
    assert str(d) == "2026-11-27"


def test_implied_move_is_beta_times_move_since_close():
    o = M.build(NOW, world(usdinr=1.0), None, india(-1.0), [], MODEL, INTR, {})
    u = next(r for r in o["factors"] if r["key"] == "usdinr")
    assert abs(u["chg_pct"] - 1.0) < 1e-6 and abs(u["effect_pct"] + 0.35) < 1e-6
    assert abs(o["implied"]["nifty_pct"] + 0.35) < 1e-3 and abs(o["implied"]["nifty_pts"] + 87.5) < 0.2       # -0.35% of 25,000
    assert o["session"] == "open" and o["ref"]["day"] == "2026-11-26"
    text = " ".join(o["reasons"])
    assert "rupee is 1.00% weaker" in text and "91 days since 2022" in text
    assert "Inside NIFTY" in text and "Oil marketers" in text


def test_live_call_branches_with_measured_rates():
    agree = M.live_call("12:20", -0.35, -1.0, INTR)
    assert agree["direction"] == "DOWN" and agree["hit"] == 58.4 and "58 times in 100" in agree["measured"]
    dis = M.live_call("12:20", 0.4, -1.0, INTR)
    assert dis["direction"] == "SIDEWAYS" and "too few days to rely on" in dis["measured"]
    assert M.live_call("12:20", 0.05, 0.1, INTR)["direction"] == "SIDEWAYS"
    assert M.live_call("09:40", 0.4, 0.0, INTR)["cut"] == "10:15"                  # before the first tested time: the 10:15 rates
    mom = M.live_call("11:30", 0.0, 0.6, INTR)
    assert mom["direction"] == "UP" and mom["hit"] == 54.0


def test_stale_feed_is_flagged_and_mcx_crude_fills_brent():
    w = world(brent=3.0)
    w["series"]["brent"] = series(90.0, 92.0, last_at=("2026-11-26", "20:00"))    # Yahoo stopped updating last night
    o = M.build(NOW, w, None, india(), [], MODEL, INTR, {})
    b = next(r for r in o["factors"] if r["key"] == "brent")
    assert b["stale"] and "not updating" in " ".join(o["reasons"]).lower() and "Brent crude (not updating)" in o["implied"]["missing"]
    ind = india()
    ind["mcx_crude"] = {"last": 7700.0, "prev": 7500.0, "symbol": "CRUDEOIL FUT"}
    o = M.build(NOW, w, None, ind, [], MODEL, INTR, {})
    b = next(r for r in o["factors"] if r["key"] == "brent")
    assert b["via"] == "MCX" and not b["stale"] and 2.6 < b["chg_pct"] < 2.7       # +2.67% in rupees, the rupee flat
    assert any(r["key"] == "mcx_crude" for r in o["factors"])


def test_headline_themes_use_whole_words():
    news = [{"time": "27 Nov 11:02", "headline": "Crude oil price rises on reports of Houthi attack on Saudi refinery", "category": "CRASH/SHOCK"},
            {"time": "27 Nov 11:05", "headline": "Nomura raises December RBI rate hike call to 50 bps", "hint": "SHORT-lean headline"},
            {"time": "26 Nov 15:00", "headline": "Rupee ends flat", "category": "MACRO"}]
    th = {t["key"]: t for t in M.themes(news, NOW)}
    assert th["crude"]["count"] == 1 and th["geo"]["count"] == 1 and th["rates"]["count"] == 1
    assert "rupee" not in th                                                          # yesterday's headline is not today's
    assert th["crude"]["neg"] == 1 and th["rates"]["neg"] == 1


def test_alerts_once_per_day_and_pushed_once():
    st = {}
    o = M.build(NOW, world(brent=2.5, usdinr=0.5), None, india(), [], MODEL, INTR, st)
    keys = {a["key"].split(":", 1)[1] for a in o["alerts"]}
    assert "brent:+1" in keys and "usdinr:+1" in keys
    first = M.pop_new(st)
    assert first and not M.pop_new(st)
    M.build(NOW + timedelta(minutes=1), world(brent=2.5, usdinr=0.5), None, india(), [], MODEL, INTR, st)
    assert not M.pop_new(st)                                                          # same level, same day: no second push


def test_pre_open_read():
    closes = {s: {"2026-11-24": 100.0, "2026-11-25": 100.0, "2026-11-26": 101.5 if s == "^GSPC" else 100.0} for s in set(M.PRE.values())}
    po = M.pre_open({"closes": closes}, MODEL, datetime(2026, 11, 27).date())
    assert po["direction"] == "UP" and abs(po["pct"] - (0.02 + 0.19 * 1.5)) < 0.01 and po["strong"] and po["hit"] == 61.3
    o = M.build(datetime(2026, 11, 27, 8, 30, tzinfo=IST), world(), {"closes": closes}, {}, [], MODEL, INTR, {})
    assert o["session"] == "pre-open" and o["call"]["direction"] == "UP" and "61 times in 100" in o["call"]["measured"]


def test_fno_view_headline_is_the_live_call():
    o = M.build(NOW, world(usdinr=1.0), None, india(-1.0), [], MODEL, INTR, {})
    cond = {"lean": 1, "confidence": "Normal", "basis": "the morning's move from the open (+0.31%)"}
    v = FV.view(NOW, 24750.0, 25000.0, {"open": 25100.0}, 15.0, {}, cond, None, {}, None, o)
    p = v["prediction"]
    assert p["direction"] == "DOWN" and p["desk_lean"] == "UP" and p["source"] == "all factors"
    text = " ".join(v["why"])
    assert "Live call, all factors" in text and "tilts toward a rise" in text
    assert not any(w.lower() in text.lower() for w in ("straddle", "delta", "theta", "sigma", "ATM"))
    assert any(f["label"] == "Live call: down" for f in v["chart"]["forecast"])
