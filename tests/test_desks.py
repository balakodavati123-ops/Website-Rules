import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import desks as D  # noqa: E402

IST = D.IST


def chain(spot=25000, step=50, iv_base=100):
    rows = []
    for k in range(int(spot - 1000), int(spot + 1000) + 1, step):
        tv = 120 * 2.718 ** (-abs(spot - k) / 150) + 1
        c, p = max(spot - k, 0) + tv, max(k - spot, 0) + tv
        mk = lambda v: {"market_data": {"ltp": v, "bid_price": round(v - 0.5, 2), "ask_price": round(v + 0.5, 2)}}
        rows.append({"strike_price": float(k), "call_options": {**mk(c), "instrument_key": f"NSE_FO|C{k}"}, "put_options": {**mk(p), "instrument_key": f"NSE_FO|P{k}"}})
    return rows


def test_fno_books_all_five_and_exits():
    book, now = D.new_book(), datetime(2026, 11, 17, 10, 0, tzinfo=IST)
    ctx = {"spot": 25150.0, "prev": 25000.0, "chains": {"2026-11-19": chain(25150)}, "expiry": "2026-11-19", "lot": 65}
    D.fno_step(book, now, ctx, set())
    names = {t["strategy"] for t in book["trades"]}
    assert {"iron_condor", "credit_spread", "long_straddle", "debit_spread", "long_breakout"} <= names
    classes = {t["risk_class"] for t in book["trades"]}
    assert classes == set(D.RISK.values())
    ic = next(t for t in book["trades"] if t["strategy"] == "iron_condor")
    assert all(l["key"].startswith("NSE_FO|") for l in ic["legs"])           # every leg carries the instrument an order needs
    assert ic["max_loss_rs"] and ic["max_gain_rs"] and ic["margin_rs"] == ic["max_loss_rs"]
    D.fno_step(book, now, ctx, set())
    assert len(book["trades"]) == 5                                   # one per strategy per day
    late = datetime(2026, 11, 17, 15, 16, tzinfo=IST)
    D.fno_step(book, late, ctx, set())
    assert all(t["status"] != "OPEN" and t["why"] for t in book["trades"])


def test_fno_target_and_stop():
    book, now = D.new_book(), datetime(2026, 11, 17, 10, 0, tzinfo=IST)
    ctx = {"spot": 25000.0, "prev": 24990.0, "chains": {"E": chain(25000)}, "expiry": "E", "lot": 65}
    D.fno_step(book, now, ctx, {"iron_condor", "long_straddle", "debit_spread", "long_breakout"})
    t = book["trades"][0]
    assert t["strategy"] == "credit_spread"
    ctx["chains"]["E"] = chain(25000)
    for r in ctx["chains"]["E"]:                                      # option prices collapse: the credit is earned
        for side in ("call_options", "put_options"):
            m = r[side]["market_data"]
            m["bid_price"], m["ask_price"] = 0.05, 0.1
    D.fno_step(book, datetime(2026, 11, 17, 11, 0, tzinfo=IST), ctx, set())
    assert t["status"] == "WIN" and t["why"] == "target"


def test_mcx_momentum_and_stop():
    book, now = D.new_book(), datetime(2026, 11, 17, 11, 0, tzinfo=IST)
    c = [{"key": "K1", "label": "Gold 1 g", "symbol": "GOLDPETAL", "mult": 1.0}]
    q = {"K1": {"last_price": 13600.0, "net_change": 130.0, "ohlc": {"high": 13605.0, "low": 13450.0}}}
    D.mcx_step(book, now, q, c, set())
    t = book["trades"][0]
    assert t["side"] == "LONG" and t["qty"] >= 1 and "0.3% of the day high" in t["reason"]
    q["K1"]["last_price"] = t["stop"] - 1
    D.mcx_step(book, now, q, c, set())
    assert t["status"] == "LOSS" and t["why"] == "stop"
    D.mcx_step(book, now, {"K1": {"last_price": 13600.0, "net_change": 130.0, "ohlc": {"high": 13605.0, "low": 13450.0}}}, c, set())
    assert len(book["trades"]) == 1                                   # same contract is not re-entered the same day


def test_crypto_breakout_target():
    book, now = D.new_book(), datetime(2026, 11, 17, 12, 0, tzinfo=IST)
    D.crypto_step(book, now, {"BTC": {"last": 65600.0, "open": 64000.0, "high": 65650.0, "low": 63800.0}}, set())
    t = book["trades"][0]
    assert t["strategy"] == "crypto_breakout" and t["side"] == "LONG"
    D.crypto_step(book, now, {"BTC": {"last": t["target_px"] + 1, "open": 64000.0, "high": 66800.0, "low": 63800.0}}, set())
    assert t["status"] == "WIN" and t["pnl_rs"] > 0


def test_learning_pauses_losers_and_gates_winners():
    losers = [{"desk": "X", "strategy": "a", "status": "LOSS", "pnl_rs": -50.0 - i % 3} for i in range(40)]
    winners = [{"desk": "X", "strategy": "b", "status": "WIN", "pnl_rs": 60.0 + i % 7} for i in range(120)]
    v = {s["strategy"]: s["verdict"] for s in D.learn(losers + winners)}
    assert v == {"a": "PAUSED", "b": "READY FOR REVIEW"}
    assert D.learn([{"desk": "X", "strategy": "c", "status": "WIN", "pnl_rs": 5.0}])[0]["verdict"] == "COLLECTING"


# ---------------------------------------------------------------- viability: real margin, weekly and monthly structures
import horizons as H  # noqa: E402
import margin as M    # noqa: E402
import thesis as T    # noqa: E402


class FakeM(M.Margin):
    def __init__(self, per_lot=40000.0):
        super().__init__("x", fn=lambda tok, legs: {"final": per_lot * (1 if len(legs) > 1 else 0.4) * (1 if legs[0][1] < 100 else 1), "required": per_lot, "legs": []})


def hchain(spot=25000, step=50):
    rows = chain(spot, step)
    for r in rows:
        k = r["strike_price"]
        for side in ("call_options", "put_options"):
            v = r[side]["market_data"]["ltp"] * 6
            r[side]["market_data"].update(ltp=round(v, 2), bid_price=round(v - 0.5, 2), ask_price=round(v + 0.5, 2))
        r["call_options"]["option_greeks"] = {"iv": 15.0, "delta": max(0.01, min(0.99, 0.5 - (k - spot) / 1500))}
        r["put_options"]["option_greeks"] = {"iv": 15.0, "delta": -max(0.01, min(0.99, 0.5 + (k - spot) / 1500))}
    return rows


def hctx(room=100000.0, score=0.1, rv=12.0, fn=None):
    rows = hchain()
    return {"u": {"NIFTY": {"spot": 25000.0, "prev": 24950.0, "exps": ["2026-11-23", "2026-12-01"]}, "BANKNIFTY": {"spot": 25000.0, "prev": 24950.0, "exps": ["2026-12-29"]}},
            "chain": lambda u, e: rows, "lot": lambda u, e: 65, "margin": fn or FakeM(), "room": [room], "env": {}, "acct": 100000.0, "vix": 15.0, "view": {"NIFTY": {"score": score, "rv": rv}, "BANKNIFTY": {"score": score, "rv": rv}}}


def test_weekly_credit_spread_booked_with_real_margin_and_thesis():
    book, now = D.new_book(), datetime(2026, 11, 18, 10, 0, tzinfo=IST)
    c = hctx()
    H.hold_step(book, now, c, set())
    t = next(x for x in book["trades"] if x["horizon"] == "weekly")
    assert t["strategy"] == "weekly_credit_spread" and t["margin_rs"] == 40000 and t["margin_src"] == "Upstox margin calculator"
    assert t["legs"][0]["kind"] == "PE" and t["legs"][0]["side"] == "S" and t["legs"][0]["strike"] < 25000          # forecast leans up: sell the put side
    th = t["thesis"]
    assert th["numbers"] and th["why"] and th["data"] and "Chance of profit" in str(th["numbers"])
    assert c["room"][0] == 20000.0                                                              # the monthly Bank Nifty structure also booked (40,000 each)
    H.hold_step(book, now, c, set())
    assert len([x for x in book["trades"] if x["horizon"] == "weekly"]) == 1                      # one per weekly expiry


def test_not_viable_when_margin_exceeds_room():
    book, now = D.new_book(), datetime(2026, 11, 18, 10, 0, tzinfo=IST)
    c = hctx(room=20000.0)
    H.hold_step(book, now, c, set())
    assert not [x for x in book["trades"] if x["horizon"] == "weekly"]
    skip = [v for v in c["margin"].log.values() if v["desk"] == "FNO"]
    assert skip and skip[0]["margin"] == 40000 and skip[0]["room"] == 20000


def test_cheap_options_without_direction_buy_a_straddle_and_no_margin_check_means_no_trade():
    book, now = D.new_book(), datetime(2026, 11, 18, 10, 0, tzinfo=IST)
    H.hold_step(book, now, hctx(score=0.05, rv=20.0), set())
    assert [x["strategy"] for x in book["trades"] if x["horizon"] == "weekly"] == ["weekly_long_straddle"]
    book2 = D.new_book()
    c = hctx(fn=M.Margin("x", fn=lambda tok, legs: (_ for _ in ()).throw(RuntimeError("down"))))
    H.hold_step(book2, now, c, set())
    assert not book2["trades"]                                                                       # margin could not be verified: nothing is traded


def test_weekly_settles_at_expiry_and_monthly_leaves_early():
    book, now = D.new_book(), datetime(2026, 11, 18, 10, 0, tzinfo=IST)
    c = hctx()
    H.hold_step(book, now, c, set())
    t = next(x for x in book["trades"] if x["horizon"] == "weekly")
    H.hold_step(book, datetime(2026, 11, 23, 15, 25, tzinfo=IST), c, set())
    assert t["status"] in ("WIN", "LOSS") and t["why"].startswith("expiry")


def test_mcx_skips_what_the_account_cannot_carry():
    book, now = D.new_book(), datetime(2026, 11, 17, 11, 0, tzinfo=IST)
    c = [{"key": "K1", "label": "Crude oil mini", "symbol": "CRUDEOILM", "mult": 10.0}]
    q = {"K1": {"last_price": 5400.0, "net_change": 60.0, "ohlc": {"high": 5402.0, "low": 5300.0}}}
    m = M.Margin("x", fn=lambda tok, legs: {"final": 24917.0 * legs[0][1], "required": 0, "legs": []})
    D.mcx_step(book, now, q, c, set(), [10000.0], {"margin": m})
    assert not book["trades"] and m.log and next(iter(m.log.values()))["margin"] == 24917
    D.mcx_step(book, now, q, c, set(), [30000.0], {"margin": m})
    t = book["trades"][0]
    assert t["margin_rs"] == 24917 and t["qty"] == 1 and t["thesis"]["viability"]


def test_desks_share_one_pool_of_cash():
    import account as A
    r = A.rooms([])
    assert r["FNO"][0] == 50000.0 and r["COMMODITY"][0] == 25000.0
    cash = [30000.0]
    a, b = A.Room(25000, cash), A.Room(25000, cash)
    a[0] -= 20000
    assert a[0] == 5000 and b[0] == 10000                      # b only has what is left of the shared cash
    b[0] -= 10000
    assert b[0] == 0 and a[0] == 0 and cash[0] == 0
