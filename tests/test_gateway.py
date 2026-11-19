import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import desks as D          # noqa: E402
import gateway as G        # noqa: E402
import indstocks as IS     # noqa: E402
import scalp as SC         # noqa: E402

IST = D.IST
NOW = datetime(2026, 11, 19, 10, 30, tzinfo=IST)
LIVE_ENV = {"EXEC_MODE": "live", "EXEC_LIVE_CONFIRM": G.CONFIRM, "INDSTOCKS_TOKEN": "tok", "EXEC_ALLOWED_IP": "1.2.3.4", "EXEC_GATE": "off", "EXEC_GATE_OFF_CONFIRM": "I-ACCEPT-UNVALIDATED-STRATEGY"}
MASTER_CSV = "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,TICK_SIZE,SERIES,FREEZE_QTY,LOT_UNITS,INTRADAY_LEVERAGE,UPPER_LIMIT,LOWER_LIMIT\nNSE,E,2885,RELIANCE,0.05,EQ,100000,1,5,1100,900\n"


def bars():
    out, px = [], 1000.0
    for i in range(30):
        px += 0.6
        o = px - 0.3
        out.append([f"09:{15 + i:02d}", o, px + 0.2, o - 0.2, px, 1000])
    px -= 2.5
    out.append(["09:45", px + 1.2, px + 1.3, px - 0.3, px, 900])
    px -= 0.8
    out.append(["09:46", px + 0.9, px + 1.0, px - 0.4, px, 800])
    o = px
    px = o + 2.6
    out.append(["09:47", o, px + 0.2, o - 0.1, px, 2200])
    return out


def paper(sym="RELIANCE", side="LONG", entry=1000.0, stop=998.0, target=1003.0, qty=100, strat="scalp_vwap_pullback", **kw):
    t = {"id": "K261119-1", "desk": "EQUITY", "strategy": strat, "label": f"{sym} {side.lower()}", "symbol": sym, "side": side, "entry": entry, "qty": qty, "stop": stop, "target_px": target, "status": "OPEN",
         "day": "2026-11-19", "opened": "10:29:00", "pnl_rs": 0.0, "hold_min": 10}
    t.update(kw)
    return t


class Fake:
    """A broker that remembers the orders it was sent and answers the order book as told."""

    def __init__(self):
        self.sent, self.cancelled, self.exits, self.book, self.ok = [], [], [], [], True

    def profile(self): return {"ok": True, "data": {"first_name": "A", "is_nse_onboarded": True}, "error": None}
    def funds(self): return {"ok": True, "data": {"detailed_avl_balance": {"eq_mis": 90000}, "realized_pnl": 0, "unrealized_pnl": 0}, "error": None}
    def margin(self, *a, **k): return {"ok": True, "data": {"total_margin": 20000}, "error": None}
    def order_book(self): return {"ok": True, "data": self.book, "error": None}

    def smart_order(self, p):
        self.sent.append(p)
        return {"ok": self.ok, "data": {"order_data": [{"order_id": "EQ-1", "order_status": "CREATED", "child_order_details": {"order_id": "GTT-1", "order_status": "CREATED"}}]}, "error": None if self.ok else "no"}

    def order(self, p):
        self.exits.append(p)
        return {"ok": True, "data": {"order_id": "EQ-2"}, "error": None}

    def cancel(self, oid, segment="EQUITY", smart=False):
        self.cancelled.append(oid)
        return {"ok": True, "data": {}, "error": None}


def gw(tmp_path, env=None, client=None):
    return G.Gateway(tmp_path / "gateway.json", client, IS.Master(MASTER_CSV), {"EXEC_MODE": "dry", **(env or {})}, ip_fn=lambda: "1.2.3.4")


# ---------------------------------------------------------------- the order itself
def test_payload_carries_a_stop_and_passes_the_reference_rules():
    c = G.cfg({})
    m = IS.Master(MASTER_CSV).get("RELIANCE")
    for side, entry, stop, tgt in (("BUY", 1000.0, 998.0, 1003.0), ("SELL", 1000.0, 1002.0, 997.0)):
        p = G.smart_payload({"id": "K1", "side": side, "entry": entry, "stop": stop, "target": tgt}, 100, m, c)
        assert G.validate_smart(p) == []
        assert p["sl_trigger_price"] and p["sl_limit_price"] and p["tgt_trigger_price"] and p["segment"] == "EQUITY" and p["product"] == "INTRADAY" and p["security_id"] == "2885"
        assert (p["sl_trigger_price"] < p["limit_price"]) == (side == "BUY") and p["remarks"] == "K1"
    assert G.validate_smart({**p, "sl_limit_price": p["sl_trigger_price"] - 1}) != []                     # a stop limit on the wrong side is caught before sending


def test_charges_make_small_trades_pointless():
    small, big = G.round_trip_cost(1000, 1003, 5, "BUY"), G.round_trip_cost(1000, 1003, 40, "BUY")
    assert small / (3 * 5) > 1.0 and big / (3 * 40) < 0.4                  # on 5 shares the charges swallow the 3-rupee target; on 40 shares they do not


def test_checks_refuse_what_is_unsafe(tmp_path):
    g = gw(tmp_path)
    c, m = {**g.c, "max_value": 200000.0}, g.mget("RELIANCE")
    base = {"id": "x", "symbol": "RELIANCE", "side": "BUY", "qty": 100, "entry": 1000.0, "stop": 998.0, "target": 1003.0}
    ok, qty = G.check(base, g.st, c, NOW, m, True)
    assert ok == [] and qty == 100
    assert any("no stop-loss" in r for r in G.check({**base, "stop": 0}, g.st, c, NOW, m, True)[0])
    assert any("wrong side" in r for r in G.check({**base, "stop": 1001.0}, g.st, c, NOW, m, True)[0])
    assert any("noise" in r for r in G.check({**base, "stop": 999.5}, g.st, c, NOW, m, True)[0])
    assert any("wider" in r for r in G.check({**base, "stop": 990.0}, g.st, c, NOW, m, True)[0])
    assert any("entry window" in r for r in G.check(base, g.st, c, datetime(2026, 11, 19, 9, 20, tzinfo=IST), m, True)[0])
    assert any("not found" in r for r in G.check({**base, "symbol": "NOPE"}, g.st, c, NOW, None, True)[0])
    big = G.check({**base, "qty": 5000}, g.st, c, NOW, m, True)[1]
    assert big == 125                                                                         # Rs 250 risk / Rs 2 stop
    assert any("charges" in r for r in G.check({**base, "qty": 5, "target": 1003.0}, g.st, c, NOW, m, True)[0])


# ---------------------------------------------------------------- the scalping agent
def test_scalp_signal_stop_and_sizing():
    b = bars()
    sig = SC.signal(b)
    assert sig and sig["side"] == "LONG"
    assert SC.signal(b[:-1] + [[*b[-1][:5], 900]]) is None                                   # no volume surge, no trade
    stop, tgt = SC.levels(sig, 1017.3, 0.05)
    assert stop < 1017.3 < tgt and (1017.3 - stop) / 1017.3 * 100 <= SC.R["stop_max"] and abs((tgt - 1017.3) / (1017.3 - stop) - 1.5) < 0.1


def test_scalp_opens_with_thesis_and_closes_net_of_charges():
    book = D.new_book()
    rows = {"RELIANCE": {"price": 1017.3, "volume": 9e6}}
    ctx = {"rows": rows, "bars": {"RELIANCE": bars()}, "room": [20000.0], "acct": 100000.0, "tick": lambda s: 0.05, "leverage": lambda s: 5.0, "news": []}
    SC.step(book, NOW, ctx)
    t = book["trades"][0]
    assert t["id"].startswith("K") and t["strategy"] == SC.STRATEGY and t["side"] == "LONG" and t["stop"] < t["entry"] < t["target_px"] and t["thesis"]["numbers"]
    assert t["qty"] * (t["entry"] - t["stop"]) <= 251 and t["margin_rs"] == round(t["qty"] * t["entry"] / 5)
    SC.step(book, NOW, ctx)
    assert len(book["trades"]) == 1                                                           # the same bar is never traded twice
    rows["RELIANCE"]["price"] = t["target_px"] + 0.1
    SC.step(book, datetime(2026, 11, 19, 10, 36, tzinfo=IST), ctx)
    gross = (t["exit"] - t["entry"]) * t["qty"]
    assert t["status"] == "WIN" and t["why"] == "target" and t["pnl_rs"] < gross and t["pnl_rs"] > 0
    rows["RELIANCE"]["price"] = 1000.0
    book["trades"].append({**t, "id": "K2", "status": "OPEN", "ts": time.time() - 1000, "entry": 1017.3, "stop": 1014.0, "target_px": 1022.0, "last": 1017.3})
    SC.step(book, datetime(2026, 11, 19, 10, 50, tzinfo=IST), ctx)
    assert book["trades"][-1]["why"] in ("stop", "time") and book["trades"][-1]["status"] == "LOSS"


# ---------------------------------------------------------------- the gateway
def test_dry_run_builds_the_order_but_sends_nothing(tmp_path):
    fake = Fake()
    g = gw(tmp_path, client=fake)
    st = g.process([paper()], [], NOW)
    it = st["intents"]["K261119-1"]
    assert st["mode"] == "dry" and it["status"] == "DRY" and it["payload"]["sl_trigger_price"] and not fake.sent
    assert it["gate"]["ok"] is False and "would be held back" in it["note"]
    t = paper(status="LOSS", pnl_rs=-250.0)
    st = g.process([t], [], NOW)
    assert st["intents"]["K261119-1"]["paper_status"] == "LOSS" and st["day"]["pnl"] == -250.0


def test_refused_intents_are_listed_with_the_reason(tmp_path):
    g = gw(tmp_path)
    st = g.process([paper(stop=None)], [], NOW)
    it = st["intents"]["K261119-1"]
    assert it["status"] == "REJECTED" and "no stop-loss" in it["reasons"][0] and "payload" not in it


def test_live_is_blocked_unless_every_condition_holds(tmp_path):
    for bad in ({"INDSTOCKS_TOKEN": ""}, {"EXEC_LIVE_CONFIRM": ""}, {"EXEC_ALLOWED_IP": "9.9.9.9"}, {"EXEC_ALLOWED_IP": ""}):
        g = gw(tmp_path, {**LIVE_ENV, **bad}, Fake())
        st = g.process([paper()], [], NOW)
        assert st["mode"] == "dry" and st["blockers"] and not g.client.sent
    g = gw(tmp_path, LIVE_ENV, Fake())
    assert g.process([], [], NOW)["mode"] == "live"


def test_gate_holds_back_an_unproven_strategy(tmp_path):
    env = {k: v for k, v in LIVE_ENV.items() if k not in ("EXEC_GATE", "EXEC_GATE_OFF_CONFIRM")}
    f = Fake()
    g = gw(tmp_path, env, f)
    st = g.process([paper()], [{"strategy": "scalp_vwap_pullback", "verdict": "COLLECTING", "closed": 5}], NOW)
    assert st["intents"]["K261119-1"]["status"] == "HELD" and not f.sent
    f2, ok = Fake(), [{"strategy": "scalp_vwap_pullback", "verdict": "WORKING", "closed": 40}]
    g2 = gw(tmp_path / "x" if False else tmp_path, env, f2)
    g2.st["intents"] = {}
    st = g2.process([paper()], ok, NOW)
    assert st["intents"]["K261119-1"]["status"] == "SENT" and f2.sent


def test_live_lifecycle_entry_stop_leg_and_exit(tmp_path):
    f = Fake()
    g = gw(tmp_path, LIVE_ENV, f)
    st = g.process([paper()], [], NOW)
    it = st["intents"]["K261119-1"]
    assert it["status"] == "SENT" and f.sent[0]["sl_trigger_price"] == 997.95 or f.sent[0]["sl_trigger_price"] < f.sent[0]["limit_price"]
    parent = {"id": "EQ-1", "remarks": "K261119-1", "status": "SUCCESS", "traded_qty": it["qty_sent"], "traded_price": "1000.1", "txn_type": "BUY"}
    child = {"id": "GTT-1", "remarks": "K261119-1", "status": "PENDING", "parent_order_id": "EQ-1", "txn_type": "SELL", "traded_qty": 0}
    f.book = [parent, child]
    st = g.process([paper()], [], NOW)
    assert st["intents"]["K261119-1"]["status"] == "PROTECTED"
    f.book = [parent, {**child, "status": "SUCCESS"}, {"id": "EQ-9", "remarks": "K261119-1", "status": "SUCCESS", "txn_type": "SELL", "traded_qty": it["qty_sent"], "traded_price": "1003.0"}]
    st = g.process([paper()], [], NOW)
    done = st["intents"]["K261119-1"]
    assert done["status"] == "EXITED" and done["pnl"] > 0 and done["pnl"] < done["gross"] and st["day"]["pnl"] == done["pnl"]


def test_missing_stop_leg_is_flattened_at_once(tmp_path):
    f = Fake()
    g = gw(tmp_path, LIVE_ENV, f)
    st = g.process([paper()], [], NOW)
    it = st["intents"]["K261119-1"]
    f.book = [{"id": "EQ-1", "remarks": "K261119-1", "status": "SUCCESS", "traded_qty": it["qty_sent"], "traded_price": "1000.0", "txn_type": "BUY"}]
    g.st["intents"]["K261119-1"]["sent_at"] = time.time() - 5
    g.process([paper()], [], NOW)
    it["filled_at"] = time.time() - 60                                                     # the stop-loss leg has not appeared for a minute
    st = g.process([paper()], [], NOW)
    assert st["intents"]["K261119-1"]["status"] == "EXITING" and f.exits and f.exits[0]["txn_type"] == "SELL" and f.exits[0]["order_type"] == "MARKET"


def test_unfilled_entry_is_cancelled_and_time_stop_exits(tmp_path):
    f = Fake()
    g = gw(tmp_path, LIVE_ENV, f)
    st = g.process([paper()], [], NOW)
    it = st["intents"]["K261119-1"]
    f.book = [{"id": "EQ-1", "remarks": "K261119-1", "status": "PENDING", "traded_qty": 0, "txn_type": "BUY"}]
    it["sent_at"] = time.time() - 120
    st = g.process([paper()], [], NOW)
    assert st["intents"]["K261119-1"]["status"] == "CANCELLING" and "EQ-1" in f.cancelled
    f.book = [{"id": "EQ-1", "remarks": "K261119-1", "status": "CANCELLED", "traded_qty": 0, "txn_type": "BUY"}]
    assert g.process([paper()], [], NOW)["intents"]["K261119-1"]["status"] == "NOFILL"
    f2 = Fake()
    g2 = gw(tmp_path / "y" if False else tmp_path, LIVE_ENV, f2)
    g2.st["intents"] = {}
    it2 = g2.process([paper(id="K9")], [], NOW)["intents"]["K9"]
    f2.book = [{"id": "EQ-1", "remarks": "K9", "status": "SUCCESS", "traded_qty": it2["qty_sent"], "traded_price": "1000", "txn_type": "BUY"}, {"id": "GTT-1", "remarks": "K9", "status": "PENDING", "parent_order_id": "EQ-1", "txn_type": "SELL"}]
    g2.process([paper(id="K9")], [], NOW)
    it2["filled_at"] = time.time() - 11 * 60
    st = g2.process([paper(id="K9")], [], NOW)
    assert st["intents"]["K9"]["status"] == "EXITING" and "GTT-1" in f2.cancelled and st["intents"]["K9"]["exit_why"] == "time stop"


def test_kill_switch_and_day_loss_stop_new_entries(tmp_path):
    (tmp_path / "KILL").write_text("")
    f = Fake()
    g = gw(tmp_path, LIVE_ENV, f)
    st = g.process([paper()], [], NOW)
    assert st["killed"] and st["intents"]["K261119-1"]["status"] == "REJECTED" and not f.sent
    (tmp_path / "KILL").unlink()
    g2 = gw(tmp_path / "z" if False else tmp_path, LIVE_ENV, Fake())
    g2.st = {"intents": {}, "events": [], "day": {"day": "2026-11-19", "trades": 0, "pnl": -1500.0, "stops": 0}, "broker": {}}
    st = g2.process([paper(id="K5")], [], NOW)
    assert st["halted"] and st["intents"]["K5"]["status"] == "REJECTED"


# ---------------------------------------------------------------- the client
def test_client_follows_the_reference_shapes():
    seen = []

    def transport(method, url, headers, body):
        seen.append((method, url, headers, body))
        if "/margin" in url:
            return 200, json.dumps({"status": "success", "data": {"total_margin": 750}}).encode()
        return 400, json.dumps({"message": "Bad Request", "debug_info": "nope", "success": False}).encode()

    c = IS.Client(" raw-token ", transport)
    r = c.margin("2885", "BUY", 10, 1000.0)
    assert r["ok"] and r["data"]["total_margin"] == 750
    method, url, headers, body = seen[0]
    assert method == "GET" and headers["Authorization"] == "raw-token" and json.loads(body)["securityID"] == "2885" and json.loads(body)["quantity"] == "10"
    bad = c.funds()
    assert not bad["ok"] and bad["error"] == "Bad Request"
    m = IS.Master(MASTER_CSV)
    assert m.get("RELIANCE") == {"id": "2885", "tick": 0.05, "freeze": 100000, "lot": 1, "leverage": 5.0, "upper": 1100.0, "lower": 900.0}
