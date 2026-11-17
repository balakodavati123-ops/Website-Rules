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
        rows.append({"strike_price": float(k), "call_options": mk(c), "put_options": mk(p)})
    return rows


def test_fno_books_all_five_and_exits():
    book, now = D.new_book(), datetime(2026, 11, 17, 10, 0, tzinfo=IST)
    ctx = {"spot": 25150.0, "prev": 25000.0, "chains": {"2026-11-19": chain(25150)}, "expiry": "2026-11-19", "lot": 65}
    D.fno_step(book, now, ctx, set())
    names = {t["strategy"] for t in book["trades"]}
    assert {"iron_condor", "credit_spread", "short_strangle", "debit_spread", "long_breakout"} <= names
    classes = {t["risk_class"] for t in book["trades"]}
    assert classes == set(D.RISK.values())
    ic = next(t for t in book["trades"] if t["strategy"] == "iron_condor")
    assert ic["max_loss_rs"] and ic["max_gain_rs"] and ic["margin_rs"] == ic["max_loss_rs"]
    D.fno_step(book, now, ctx, set())
    assert len(book["trades"]) == 5                                   # one per strategy per day
    late = datetime(2026, 11, 17, 15, 16, tzinfo=IST)
    D.fno_step(book, late, ctx, set())
    assert all(t["status"] != "OPEN" and t["why"] for t in book["trades"])


def test_fno_target_and_stop():
    book, now = D.new_book(), datetime(2026, 11, 17, 10, 0, tzinfo=IST)
    ctx = {"spot": 25000.0, "prev": 24990.0, "chains": {"E": chain(25000)}, "expiry": "E", "lot": 65}
    D.fno_step(book, now, ctx, {"iron_condor", "short_strangle", "debit_spread", "long_breakout"})
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
