"""The order desk (backend/executor.py): nothing reaches the broker without the CEO's approval, nothing beyond the wallet, and exits
always follow. The broker is a fake that records every call."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import executor as X  # noqa: E402

NOW = datetime(2026, 11, 30, 10, 0, tzinfo=X.IST)
STATS = [{"strategy": "long_straddle", "verdict": "READY FOR REVIEW"}, {"strategy": "price_only", "verdict": "READY FOR REVIEW"},
         {"strategy": "spread", "verdict": "READY FOR REVIEW"}]


def straddle(status="OPEN", qty=2, **k):
    t = {"id": "F261130-1", "desk": "FNO", "strategy": "long_straddle", "label": "NIFTY long straddle", "side": "LONG", "qty": qty, "lot": 65, "status": status,
         "day": "2026-11-30", "opened": "10:00:00", "legs": [{"side": "B", "kind": "CE", "entry": 150.0, "last": 150.0, "key": "NSE_FO|1"},
                                                             {"side": "B", "kind": "PE", "entry": 170.0, "last": 170.0, "key": "NSE_FO|2"}]}
    t.update(k)
    return t


def stock(status="OPEN", **k):
    t = {"id": "E261130-1", "desk": "EQUITY", "strategy": "price_only", "label": "HAL long", "side": "LONG", "entry": 4800.0, "last": 4800.0, "qty": 10,
         "status": status, "day": "2026-11-30", "opened": "10:30:00", "symbol": "HAL", "horizon": "intraday"}
    t.update(k)
    return t


class Broker:
    """Fake Upstox: funds, order placement (fills as told), order details, cancel."""
    def __init__(self, cash=100000.0, fill=True):
        self.cash, self.fill, self.calls, self.orders = cash, fill, [], {}

    def __call__(self, method, url, token, body=None, algo=""):
        self.calls.append((method, url, body, algo))
        if "get-funds-and-margin" in url:
            return 200, {"data": {"equity": {"available_margin": self.cash}}}
        if url.endswith("/order/place"):
            oid = f"o{len(self.orders) + 1}"
            self.orders[oid] = dict(body, filled=body["quantity"] if self.fill else 0)
            return 200, {"status": "success", "data": {"order_ids": [oid]}}
        if "/order/details" in url:
            o = self.orders[url.split("order_id=")[1]]
            return 200, {"data": {"status": "complete" if o["filled"] else "open", "filled_quantity": o["filled"], "average_price": o["price"] if o["filled"] else 0}}
        if "/order/cancel" in url:
            o = self.orders[url.split("order_id=")[1]]
            o["cancelled"] = True
            return 200, {"data": {}}
        return 404, {}

    def placed(self):
        return [c[2] for c in self.calls if c[1].endswith("/order/place")]


LIVE = {"EXEC_MODE": "live", "UPSTOX_EXEC_TOKEN": "t", "EXEC_LIVE_CONFIRM": "I-UNDERSTAND-REAL-MONEY", "EXEC_ALGO_NAME": "desk1"}


def run(trades, p, b, env, now=NOW, live_ok=("long_straddle", "price_only", "spread"), margin=None, pushes=None):
    deps = {"env": env, "call": b, "margin": margin or (lambda legs: sum(1000.0 if s == "BUY" else 500.0 for _, q, s in legs)),
            "key_of": lambda s: "NSE_EQ|" + s, "push": (lambda *a: pushes.append(a)) if pushes is not None else None}
    return X.step(trades, STATS, set(live_ok), p, now, deps)


def test_off_sends_nothing(tmp_path):
    b = Broker()
    st = run([straddle()], tmp_path / "o.json", b, {})
    assert b.calls == [] and st["mode"] == "off" and not st["tickets"]


def test_nothing_is_sent_without_approval(tmp_path):
    b, p, pushes = Broker(), tmp_path / "o.json", []
    st = run([straddle()], p, b, LIVE, pushes=pushes)
    tk = next(iter(st["tickets"].values()))
    assert tk["status"] == "AWAITING" and b.placed() == [] and pushes and "Approve order" in pushes[0][0]
    for k in range(1, 4):                                                  # minutes pass, no approval: still nothing
        run([straddle()], p, b, LIVE, now=NOW + timedelta(minutes=k))
    assert b.placed() == []
    st = run([straddle()], p, b, LIVE, now=NOW + timedelta(minutes=6))
    assert next(iter(st["tickets"].values()))["status"] == "EXPIRED" and b.placed() == []
    assert "expired" in X.approve(p, tk["id"], NOW + timedelta(minutes=7))


def test_approved_order_is_sized_by_the_wallet_and_sent(tmp_path):
    b, p = Broker(cash=2500.0), tmp_path / "o.json"                         # 90% of 2,500 = 2,250: one lot at 2,000 (two bought legs at 1,000)
    st = run([straddle(qty=2)], p, b, LIVE)
    tk = next(iter(st["tickets"].values()))
    assert tk["n"] == 1 and tk["cost"] == 2000 and "cut from 2 to 1" in tk["note"] and [lg["qty"] for lg in tk["legs"]] == [65, 65]
    assert "Approved" in X.approve(p, tk["id"], NOW + timedelta(minutes=1))
    st = run([straddle()], p, b, LIVE, now=NOW + timedelta(minutes=1))
    placed = b.placed()
    assert [o["transaction_type"] for o in placed] == ["BUY", "BUY"] and all(o["quantity"] == 65 and o["order_type"] == "LIMIT" for o in placed)
    assert all(c[3] == "desk1" for c in b.calls if c[1].endswith("/order/place"))                 # the algo name rides on every order
    assert placed[0]["price"] >= 150 * 1.003
    st = run([straddle()], p, b, LIVE, now=NOW + timedelta(minutes=1, seconds=10))
    assert st["tickets"][tk["id"]]["status"] == "OPEN" and st["tickets"][tk["id"]]["filled"] == [65, 65]


def test_no_ticket_when_one_lot_does_not_fit(tmp_path):
    b = Broker(cash=1500.0)
    st = run([straddle()], tmp_path / "o.json", b, LIVE)
    assert not st["tickets"] and "wallet" in st["held"][0]["why"] and "needs Rs 2,000" in st["held"][0]["why"]


def test_gates(tmp_path):
    b, p = Broker(), tmp_path / "o.json"
    st = run([straddle()], p, b, LIVE, live_ok=())
    assert "not approved for live" in st["held"][0]["why"] and not st["tickets"]
    st = run([straddle()], p, b, {**LIVE, "EXEC_LIVE_CONFIRM": ""})
    assert "EXEC_LIVE_CONFIRM" in st["note"] and not st["tickets"]
    (tmp_path / "KILL").write_text("")
    st = run([straddle()], p, b, LIVE)
    assert "kill switch" in st["held"][0]["why"] and not st["tickets"]
    (tmp_path / "KILL").unlink()
    st = X.step([straddle()], [], {"long_straddle"}, p, NOW, {"env": LIVE, "call": b, "margin": lambda legs: 1000.0})
    assert "READY FOR REVIEW" in st["held"][0]["why"]                     # strict gate by default
    env = {**LIVE, "EXEC_GATE": "ceo", "EXEC_GATE_CONFIRM": "I-ACCEPT-UNVALIDATED-STRATEGY"}
    st = X.step([straddle()], [], {"long_straddle"}, p, NOW, {"env": env, "call": b, "margin": lambda legs: 1000.0})
    assert st["tickets"]                                                   # your deliberate override
    assert b.placed() == []


def test_price_moved_cancels_before_sending(tmp_path):
    b, p = Broker(), tmp_path / "o.json"
    st = run([straddle()], p, b, LIVE)
    tid = next(iter(st["tickets"]))
    X.approve(p, tid, NOW)
    up = straddle(legs=[{"side": "B", "kind": "CE", "entry": 150.0, "last": 153.0, "key": "NSE_FO|1"}, {"side": "B", "kind": "PE", "entry": 170.0, "last": 170.0, "key": "NSE_FO|2"}])
    st = run([up], p, b, LIVE, now=NOW + timedelta(seconds=30))
    assert st["tickets"][tid]["status"] == "CANCELLED" and "moved" in st["tickets"][tid]["why"] and b.placed() == []


def test_exit_needs_no_second_approval_and_follows_the_fill(tmp_path):
    b, p = Broker(), tmp_path / "o.json"
    st = run([stock()], p, b, LIVE)
    tid = next(iter(st["tickets"]))
    X.approve(p, tid, NOW)
    run([stock()], p, b, LIVE, now=NOW + timedelta(seconds=10))
    run([stock()], p, b, LIVE, now=NOW + timedelta(seconds=20))
    st = run([stock("WIN", last=4850.0)], p, b, LIVE, now=NOW + timedelta(minutes=30))
    placed = b.placed()
    assert [o["transaction_type"] for o in placed] == ["BUY", "SELL"] and placed[1]["quantity"] == placed[0]["quantity"]
    st = run([stock("WIN", last=4850.0)], p, b, LIVE, now=NOW + timedelta(minutes=30, seconds=10))
    tk = st["tickets"][tid]
    assert tk["status"] == "CLOSED" and tk["pnl"] > 0


def test_unfilled_entry_is_cancelled(tmp_path):
    b, p = Broker(fill=False), tmp_path / "o.json"
    st = run([stock()], p, b, LIVE)
    tid = next(iter(st["tickets"]))
    X.approve(p, tid, NOW)
    run([stock()], p, b, LIVE, now=NOW + timedelta(seconds=5))
    st = run([stock()], p, b, LIVE, now=NOW + timedelta(seconds=90))
    assert any("/order/cancel" in c[1] for c in b.calls)
    assert st["tickets"][tid]["status"] in ("SENDING", "CANCELLED")
    orig = b.__call__                                                       # Upstox now reports the order cancelled

    def cancelled(method, url, token, body=None, algo=""):
        if "/order/details" in url:
            return 200, {"data": {"status": "cancelled", "filled_quantity": 0, "average_price": 0}}
        return orig(method, url, token, body, algo)
    st = run([stock()], p, cancelled, LIVE, now=NOW + timedelta(seconds=100))
    assert st["tickets"][tid]["status"] == "CANCELLED"


def test_spread_sells_only_after_the_buy_fills(tmp_path):
    b, p = Broker(), tmp_path / "o.json"
    t = straddle(id="F261130-2", strategy="spread", label="NIFTY call spread", qty=1,
                 legs=[{"side": "S", "kind": "CE", "entry": 60.0, "last": 60.0, "key": "NSE_FO|9"}, {"side": "B", "kind": "CE", "entry": 150.0, "last": 150.0, "key": "NSE_FO|1"}])
    st = run([t], p, b, LIVE)
    tid = next(iter(st["tickets"]))
    X.approve(p, tid, NOW)
    run([t], p, b, LIVE, now=NOW + timedelta(seconds=5))
    assert [o["transaction_type"] for o in b.placed()] == ["BUY"]          # the short leg waits for the long one
    run([t], p, b, LIVE, now=NOW + timedelta(seconds=10))
    assert [o["transaction_type"] for o in b.placed()] == ["BUY", "SELL"]
    run([t], p, b, LIVE, now=NOW + timedelta(seconds=15))
    run([dict(t, status="LOSS")], p, b, LIVE, now=NOW + timedelta(minutes=20))
    assert [o["transaction_type"] for o in b.placed()][2] == "BUY"         # on exit the short leg is bought back first


def test_switching_off_still_manages_open_positions(tmp_path):
    b, p = Broker(), tmp_path / "o.json"
    st = run([stock()], p, b, LIVE)
    tid = next(iter(st["tickets"]))
    X.approve(p, tid, NOW)
    run([stock()], p, b, LIVE, now=NOW + timedelta(seconds=10))
    run([stock()], p, b, LIVE, now=NOW + timedelta(seconds=20))
    st = run([stock("LOSS", last=4700.0)], p, b, {"UPSTOX_EXEC_TOKEN": "t"}, now=NOW + timedelta(minutes=5))
    assert "still managed" in st["note"] and b.placed()[-1]["transaction_type"] == "SELL"


def test_sandbox_uses_its_own_token_and_host(tmp_path):
    b, p = Broker(), tmp_path / "o.json"
    env = {"EXEC_MODE": "sandbox", "UPSTOX_SANDBOX_TOKEN": "s"}
    st = run([stock()], p, b, env)
    tid = next(iter(st["tickets"]))
    assert st["wallet"]["available"] == 100000.0                          # practice wallet without an account token
    X.approve(p, tid, NOW)
    run([stock()], p, b, env, now=NOW + timedelta(seconds=10))
    assert any(c[1] == "https://api-sandbox.upstox.com/v3/order/place" for c in b.calls)


def test_static_ip_refusal_is_explained(tmp_path):
    p = tmp_path / "o.json"
    base = Broker()

    def refuse(method, url, token, body=None, algo=""):
        if url.endswith("/order/place"):
            return 403, {"status": "error", "errors": [{"errorCode": "UDAPI1154", "message": "blocked"}]}
        return base(method, url, token, body, algo)
    st = run([stock()], p, refuse, LIVE)
    tid = next(iter(st["tickets"]))
    X.approve(p, tid, NOW)
    st = run([stock()], p, refuse, LIVE, now=NOW + timedelta(seconds=10))
    assert st["tickets"][tid]["status"] == "FAILED" and "static IP" in st["tickets"][tid]["why"] and st["summary"]["static_ip_refused"]
