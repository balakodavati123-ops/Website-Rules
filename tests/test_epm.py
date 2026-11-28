"""EPM (backend/epm.py): option pricing, implied volatility, trading time, the expected move, target / stop / if-flat per strike, and the
open-trade scenarios on the F&O tab."""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import epm as EPM         # noqa: E402
import fno_view as FV     # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
FRI = datetime(2026, 11, 27, 14, 0, tzinfo=IST)
TUE = date(2026, 12, 1)


def test_pricing_parity_and_implied_vol_round_trip():
    T = EPM.years(840)
    c, p = EPM.bs(25600, 25600, T, 0.15, "CE"), EPM.bs(25600, 25600, T, 0.15, "PE")
    assert abs(c - p) < 1e-6                                              # at the money, rate zero: call = put
    assert abs((EPM.bs(25600, 25500, T, 0.15, "CE") - EPM.bs(25600, 25500, T, 0.15, "PE")) - 100) < 1e-6
    assert abs(EPM.implied_vol(c, 25600, 25600, T, "CE") - 0.15) < 1e-4
    assert EPM.implied_vol(99.0, 25600, 25500, T, "CE") is None           # below intrinsic value: no volatility explains it


def test_trading_time():
    assert EPM.minutes_left(FRI) == 90 and EPM.minutes_left(FRI.replace(hour=16)) == 0
    assert EPM.trading_minutes_to(TUE, FRI) == 90 + 375 + 375              # Friday's last 90 minutes, Monday, Tuesday (weekend counts as no time)
    assert EPM.trading_minutes_to(TUE, FRI, {"2026-11-30"}) == 90 + 375    # a holiday Monday
    assert abs(EPM.expected_move(25600, 0.16, 375) - 25600 * 0.16 / 252 ** 0.5) < 1e-6


def _rows(S=25600.0, F=25620.0, iv=0.15, T_min=840):
    T = EPM.years(T_min)
    return [{"k": k, "ce": round(EPM.bs(F, k, T, iv + (k - S) / 100000, "CE"), 2), "pe": round(EPM.bs(F, k, T, iv + (k - S) / 100000, "PE"), 2)} for k in range(25300, 25950, 50)]


def test_chain_targets_stops_and_forward():
    res = EPM.chain(_rows(), 25600.0, TUE, FRI, 65)
    m = res["meta"]
    assert m["ok"] and abs(m["forward"] - 25620) < 1 and abs(m["atm_iv"] - 15.0) < 0.3
    assert set(m["moves"]) == {"today", "session", "expiry"} and m["moves"]["today"] < m["moves"]["session"] < m["moves"]["expiry"]
    atm = res["strikes"][25600]
    for kind in ("ce", "pe"):
        e = atm[kind]["today"]
        assert e["target"] > atm[kind]["px"] > e["stop"] > 0 and e["if_flat"] < atm[kind]["px"]           # time decay when NIFTY stays put
        assert e["gain_rs"] == round(e["gain"] * 65) and e["loss_rs"] == round(e["loss"] * 65)
    assert atm["ce"]["expiry"]["stop"] < atm["ce"]["today"]["stop"]                # a longer horizon: a bigger move and more decay
    assert abs(atm["ce"]["iv"] - atm["pe"]["iv"]) < 0.3                            # priced off the forward, a strike's call and put agree
    closed = EPM.chain(_rows(), 25600.0, TUE, FRI.replace(hour=16), 65)
    assert "today" not in closed["meta"]["moves"] and "session" in closed["meta"]["moves"]


def _snap_side(px):
    return {"instrument_key": "k", "market_data": {"ltp": px, "bid_price": px - 0.5, "ask_price": px + 0.5, "bid_qty": 75, "ask_qty": 75}, "option_greeks": {}}


def test_chain_snapshot_and_open_trade_scenarios():
    rows = [{"strike_price": float(r["k"]), "call_options": _snap_side(r["ce"]), "put_options": _snap_side(r["pe"])} for r in _rows()]
    snap = FV.chain_snapshot(rows, 25600.0, "2026-12-01", 65, FRI)
    assert snap["epm"]["ok"] and snap["rows"][0]["ce"]["epm"]["today"]["target"] > snap["rows"][0]["ce"]["epm"]["px"]
    straddle = {"id": "F1", "desk": "FNO", "status": "OPEN", "expiry": "2026-12-01", "lot": 65, "qty": 1,
                "legs": [{"side": "B", "strike": 25600.0, "kind": "CE"}, {"side": "B", "strike": 25600.0, "kind": "PE"}]}
    call = dict(straddle, id="F2", legs=[{"side": "B", "strike": 25600.0, "kind": "CE"}])
    x = FV.trade_epm([straddle, call], {"2026-12-01": rows}, 25600.0, FRI)
    s, c = x["F1"]["pnl_if"], x["F2"]["pnl_if"]
    assert s["flat"] < 0 and s["up"] > s["flat"] and s["down"] > s["flat"]       # a bought pair wants a move either way and pays decay if flat
    assert c["up"] > 0 > c["down"] and x["F2"]["legs"][0]["target"] > x["F2"]["legs"][0]["now"] > x["F2"]["legs"][0]["stop"]
    assert x["F2"]["horizon"] == "rest of today"
