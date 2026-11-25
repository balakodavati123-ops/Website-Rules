import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import fno_view as FV     # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
JARGON = ("straddle", "delta", "theta", "gamma", "vega", "implied", "IV ", "lean", "ATM", "OTM", "ITM", "sigma", "%ile", "percentile")


def _view(at="11:00", lean=1, decided=True, vix=15.0):
    now = datetime(2026, 11, 25, *map(int, at.split(":")), tzinfo=IST)
    cond = {"lean": lean, "confidence": "Normal", "basis": "the morning's move from the open (+0.31%)", "news_against": 0}
    dec = {"day": "2026-11-25", "at": "10:00", "spot": 25440.0, "conditions": cond} if decided else None
    return FV.view(now, 25480.0, 25350.0, {"open": 25400.0, "high": 25500.0, "low": 25380.0}, vix, {"vix_chg": 4.0, "gap": 0.2}, cond, dec,
                   {"strong": 5, "net": 3, "macro": ["RBI keeps rates unchanged"], "mood": "cautious", "fc": 0.3})


def test_plain_words_view_up_day():
    v = _view()
    assert v["mode"]["name"] == "Volatile" and v["mode"]["code"] == "MODE_2_VOLATILE"
    assert v["prediction"]["direction"] == "UP" and v["final"] and v["status"].startswith("Decided at 10:00")
    text = " ".join(v["why"]) + " " + v["plan"]
    assert "up 130 points" in text and "opened 50 points higher" in text and "risen 80 points" in text
    assert "4 good and 1 bad" in text and "RBI keeps rates unchanged" in text and "forecast team's view is positive" in text
    assert not [j for j in JARGON if j.lower() in text.lower()], [j for j in JARGON if j.lower() in text.lower()]
    lo, hi = v["prediction"]["day_range"]
    assert hi - 25350 == 25350 - lo and 230 < hi - 25350 < 245                           # 25350 x 15% / sqrt(252) = 239.5 points
    fc = {f["label"]: f["px"] for f in v["chart"]["forecast"]}
    assert fc["Likely high by close"] > fc["Desk's call: up"] > 25480 > fc["Likely low by close"]
    assert [l["label"] for l in v["chart"]["levels"]] == ["Yesterday's close", "Today's open", "Desk decided here (10:00)"]


def test_early_read_and_no_direction():
    v = _view(at="09:40", lean=0, decided=False, vix=12.0)
    assert v["status"].startswith("Early read") and not v["final"] and v["mode"]["name"] == "Quiet"
    assert v["prediction"]["direction"] == "SIDEWAYS" and not [f for f in v["chart"]["forecast"] if "call" in f["label"]]
    assert FV.mode(19.5)["code"] == "MODE_3_HIGH_VOLATILITY" and FV.minutes_left(datetime(2026, 11, 25, 15, 0)) == 30


def test_chain_snapshot_keeps_strikes_round_the_money_with_depth():
    rows = [{"strike_price": float(k), "call_options": {"instrument_key": f"C{k}", "market_data": {"ltp": 100.0, "bid_price": 99.5, "bid_qty": 650, "ask_price": 100.5, "ask_qty": 325,
                                                                                                "volume": 1000, "oi": 5000, "prev_oi": 4000, "close_price": 90.0}, "option_greeks": {"iv": 14.1}},
             "put_options": {"instrument_key": f"P{k}", "market_data": {"ltp": 80.0, "bid_price": 79.5, "ask_price": 80.5, "oi": 3000, "prev_oi": 3500}}} for k in range(24000, 27001, 50)]
    keys = FV.depth_keys(rows, 25480)
    assert set(keys) == {f"{s}{k}" for s in "CP" for k in (25400, 25450, 25500, 25550, 25600)}
    q = {"C25500": {"depth": {"buy": [{"price": 99.5, "quantity": 650, "orders": 3}] * 6, "sell": [{"price": 100.5, "quantity": 325, "orders": 1}]}, "total_buy_quantity": 9000}}
    snap = FV.chain_snapshot(rows, 25480.0, "2026-12-01", 65, datetime(2026, 11, 25, 11, 0, tzinfo=IST), q)
    assert snap["atm"] == 25500 and len(snap["rows"]) == 21 and snap["rows"][0]["k"] == 25000 and snap["rows"][-1]["k"] == 26000
    r = next(x for x in snap["rows"] if x["k"] == 25500)
    assert r["ce"]["doi"] == 1000 and r["pe"]["doi"] == -500 and r["ce"]["bq"] == 650 and r["ce"]["key"] == "C25500"
    assert len(snap["depth"]["C25500"]["buy"]) == 5 and snap["depth"]["C25500"]["tbq"] == 9000
