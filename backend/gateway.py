"""The gateway between the trading agents and the broker (INDstocks / INDmoney). Every order an agent wants goes through here.

An agent hands over an intent: instrument, side, size, entry, stop-loss and target. The gateway refuses it unless it passes the
pre-trade checks (a stop-loss on the right side and a sensible distance away, risk and order-value caps, trading window, open
position and daily limits, charges small enough against the target, the instrument and price band, and margin when the broker can be asked).
An approved intent becomes ONE smart order: the entry plus a broker-side stop-loss (and target) leg that the exchange holds, so the
position is protected even if this program stops. After the entry fills the gateway confirms the stop-loss leg exists and flattens the
position at once if it does not; it cancels an entry that has not filled, exits on a time stop and at the end of the day, and halts new
entries after a daily loss limit or on the kill switch.

Modes (EXEC_MODE): dry (default; checks and builds the exact order, sends nothing) | live | off.
Live needs ALL of: EXEC_MODE=live, EXEC_LIVE_CONFIRM=I-UNDERSTAND-REAL-MONEY, INDSTOCKS_TOKEN, this machine's public IP equal to
EXEC_ALLOWED_IP (the static IP whitelisted on the INDstocks dashboard; order placement is refused by the broker from any other address),
and the agent's paper record to pass the gate (EXEC_GATE: normal = verdict WORKING with at least 30 closed paper trades, strict = READY
FOR REVIEW). Kill switch: EXEC_KILL=1 or a file named KILL in the data folder.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
CONFIRM = "I-UNDERSTAND-REAL-MONEY"
OPEN_STATES = ("SENT", "FILLED", "PROTECTED", "EXITING", "CANCELLING")
DEAD = ("CANCELLED", "FAILED", "EXPIRED", "ABORTED", "REJECTED")
NOT_INTRADAY = ("swing", "signal", "weekly")


def is_dead(status) -> bool:
    s = str(status or "")
    return s in DEAD or s.endswith("CANCELLED") or s.endswith("EXPIRED")


def cfg(env: dict | None = None) -> dict:
    e = os.environ if env is None else env
    f = lambda k, d: float(e.get(k) or d)
    return {"mode": (e.get("EXEC_MODE") or "dry").lower(), "token": (e.get("INDSTOCKS_TOKEN") or "").strip(), "live_ok": e.get("EXEC_LIVE_CONFIRM", "") == CONFIRM,
            "allowed_ip": (e.get("EXEC_ALLOWED_IP") or "").strip(), "gate": (e.get("EXEC_GATE") or "normal").lower(), "gate_off_ok": e.get("EXEC_GATE_OFF_CONFIRM", "") == "I-ACCEPT-UNVALIDATED-STRATEGY",
            "kill": e.get("EXEC_KILL") == "1", "algo": (e.get("EXEC_ALGO_ID") or "").strip(),
            "max_value": f("EXEC_MAX_ORDER_RS", 40000), "risk": f("EXEC_RISK_PER_TRADE_RS", 250), "max_day_loss": f("EXEC_MAX_DAY_LOSS_RS", 1000),
            "max_open": int(f("EXEC_MAX_OPEN", 3)), "max_trades": int(f("EXEC_MAX_TRADES_DAY", 12)), "sl_min": f("EXEC_SL_MIN_PCT", 0.10), "sl_max": f("EXEC_SL_MAX_PCT", 0.60),
            "min_rc": f("EXEC_MIN_REWARD_TO_COST", 3.0), "first": e.get("EXEC_FIRST_ENTRY") or "09:30", "last": e.get("EXEC_LAST_ENTRY") or "14:45", "squareoff": e.get("EXEC_SQUAREOFF") or "15:10",
            "parent_timeout": f("EXEC_PARENT_TIMEOUT_S", 45), "prot_wait": f("EXEC_PROTECTION_WAIT_S", 20), "buffer": f("EXEC_ENTRY_BUFFER", 0.0005), "sl_gap": f("EXEC_SL_LIMIT_GAP", 0.002),
            "gate_min": int(f("EXEC_GATE_MIN_TRADES", 30)), "agents": [a.strip() for a in (e.get("EXEC_AGENTS") or "scalp_vwap_pullback").split(",") if a.strip()]}


def public_ip() -> str | None:
    try:
        return urllib.request.urlopen("https://api.ipify.org", timeout=8).read().decode().strip()
    except Exception:
        return None


def resolve_mode(c: dict, ip: str | None) -> tuple[str, list[str]]:
    """The mode that will really run, and why live is blocked when it was asked for."""
    if c["mode"] != "live":
        return ("off" if c["mode"] == "off" else "dry"), []
    why = []
    if not c["token"]:
        why.append("INDSTOCKS_TOKEN is not set")
    if not c["live_ok"]:
        why.append("EXEC_LIVE_CONFIRM is not set to the confirmation phrase")
    if not c["allowed_ip"]:
        why.append("EXEC_ALLOWED_IP (the static IP whitelisted at INDstocks) is not set")
    elif ip != c["allowed_ip"]:
        why.append(f"this machine's public IP is {ip or 'unknown'}, not the whitelisted {c['allowed_ip']}")
    return ("live" if not why else "dry"), why


# ---------------------------------------------------------------- prices and costs
def rnd_up(x: float, tick: float) -> float: return round(math.ceil(round(x / tick, 6)) * tick, 2)
def rnd_dn(x: float, tick: float) -> float: return round(math.floor(round(x / tick, 6)) * tick, 2)


def charges(buy_val: float, sell_val: float, orders: int = 2) -> float:
    """Estimated intraday cash-equity charges for one round trip: flat Rs 10 an order, STT on the sell side, exchange and SEBI fees, stamp duty on the buy side, GST on brokerage and fees."""
    brok, stt, exch, sebi, stamp = 10.0 * orders, 0.00025 * sell_val, 0.0000297 * (buy_val + sell_val), 0.000001 * (buy_val + sell_val), 0.00003 * buy_val
    return round(brok + stt + exch + sebi + stamp + 0.18 * (brok + exch + sebi), 2)


def round_trip_cost(entry: float, exit_px: float, qty: int, side: str) -> float:
    buy, sell = (entry * qty, exit_px * qty) if side == "BUY" else (exit_px * qty, entry * qty)
    return charges(buy, sell)


# ---------------------------------------------------------------- the order itself
def smart_payload(i: dict, qty: int, m: dict | None, c: dict) -> dict:
    """The exact INDstocks /smart/order body: a limit entry with a stop-loss leg and, when the agent set one, a target leg."""
    tick, buy = (m or {}).get("tick") or 0.05, i["side"] == "BUY"
    lim = rnd_up(i["entry"] * (1 + c["buffer"]), tick) if buy else rnd_dn(i["entry"] * (1 - c["buffer"]), tick)
    slt = rnd_dn(i["stop"], tick) if buy else rnd_up(i["stop"], tick)
    gap = max(tick, rnd_up(slt * c["sl_gap"], tick))               # the limit sits this far beyond the trigger so a fast move still fills
    p = {"txn_type": i["side"], "exchange": "NSE", "segment": "EQUITY", "product": "INTRADAY", "order_type": "LIMIT", "validity": "DAY", "security_id": str((m or {}).get("id") or ""), "qty": int(qty),
         "limit_price": lim, "sl_trigger_price": slt, "sl_limit_price": round(slt - gap if buy else slt + gap, 2), "remarks": str(i["id"])[:100]}
    if i.get("target"):
        tt = rnd_dn(i["target"], tick) if buy else rnd_up(i["target"], tick)
        p.update(tgt_trigger_price=tt, tgt_limit_price=round(tt + tick if buy else tt - tick, 2))     # the reference puts the target limit beyond its trigger
    if c["algo"]:
        p["algo_id"] = c["algo"]
    return p


def validate_smart(p: dict, tick: float = 0.05) -> list[str]:
    """The reference's own rules for where the legs must sit, checked before anything is sent."""
    out, buy = [], p["txn_type"] == "BUY"
    e, slt, sll = p["limit_price"], p.get("sl_trigger_price"), p.get("sl_limit_price")
    if not p.get("security_id"):
        out.append("no security_id")
    if not slt or not sll:
        out.append("a stop-loss leg needs both its trigger and its limit price")
        return out
    if (buy and not slt < e) or (not buy and not slt > e):
        out.append("stop-loss trigger must sit below the entry on a BUY and above it on a SELL")
    if (buy and not sll < slt) or (not buy and not sll > slt):
        out.append("stop-loss limit must sit beyond its trigger")
    if p.get("tgt_trigger_price"):
        tt, tl = p["tgt_trigger_price"], p["tgt_limit_price"]
        if (buy and not tt > e) or (not buy and not tt < e):
            out.append("target trigger must sit above the entry on a BUY and below it on a SELL")
        if (buy and not tl > tt) or (not buy and not tl < tt):
            out.append("target limit must sit beyond its trigger")
    for k in ("limit_price", "sl_trigger_price", "sl_limit_price", "tgt_trigger_price", "tgt_limit_price"):
        if p.get(k) and abs(p[k] / tick - round(p[k] / tick)) > 1e-6:
            out.append(f"{k} is not a multiple of the tick size {tick}")
    return out


# ---------------------------------------------------------------- the gate and the checks
def gate_ok(agent: str, stats: list[dict], c: dict) -> tuple[bool, str]:
    s = next((x for x in stats if x["strategy"] == agent), None)
    v, n = (s["verdict"], s["closed"]) if s else ("COLLECTING", 0)
    if c["gate"] == "off":
        return c["gate_off_ok"], "gate is off" if c["gate_off_ok"] else "EXEC_GATE=off also needs EXEC_GATE_OFF_CONFIRM"
    if c["gate"] == "strict":
        return v == "READY FOR REVIEW", f"verdict {v} ({n} closed paper trades); strict gate needs READY FOR REVIEW"
    return (v in ("WORKING", "READY FOR REVIEW") and n >= c["gate_min"]), f"verdict {v} with {n} closed paper trades; needs WORKING and {c['gate_min']}+"


def check(i: dict, st: dict, c: dict, now: datetime, m: dict | None, have_master: bool, funds: float | None = None, margin: float | None = None) -> tuple[list[str], int]:
    """Reasons the intent is refused (empty when approved) and the size the gateway will actually send."""
    r, side, e, s, tg = [], i["side"], float(i["entry"] or 0), float(i.get("stop") or 0), i.get("target")
    if e <= 0:
        r.append("no entry price")
    if not s:
        r.append("no stop-loss: every order must carry one")
    elif e > 0:
        if (side == "BUY" and s >= e) or (side == "SELL" and s <= e):
            r.append("stop-loss is on the wrong side of the entry")
        else:
            d = abs(e - s) / e * 100
            if d < c["sl_min"]:
                r.append(f"stop-loss is only {d:.2f}% away, inside normal price noise (minimum {c['sl_min']}%)")
            if d > c["sl_max"]:
                r.append(f"stop-loss is {d:.2f}% away, wider than the {c['sl_max']}% maximum for a scalp")
    if tg and e > 0 and s:
        if (side == "BUY" and tg <= e) or (side == "SELL" and tg >= e):
            r.append("target is on the wrong side of the entry")
        elif abs(tg - e) < 1.2 * abs(e - s):
            r.append("target is less than 1.2 times the risk")
    if have_master and not m:
        r.append("instrument not found in the INDstocks instrument master")
    qty = int(i.get("qty") or 0)
    if e > 0 and s:
        qty = min(qty, int(c["risk"] // max(abs(e - s), 1e-9)), int(c["max_value"] // e))
        if m and m.get("freeze"):
            qty = min(qty, int(m["freeze"]) - 1)
    if qty < 1:
        r.append(f"size is below one share once the Rs {c['risk']:,.0f} risk cap and Rs {c['max_value']:,.0f} order cap are applied")
    hhmm = now.strftime("%H:%M")
    if not (c["first"] <= hhmm <= c["last"]):
        r.append(f"outside the entry window {c['first']} to {c['last']}")
    live = [x for x in st["intents"].values() if x["status"] in OPEN_STATES or (x["status"] == "DRY" and x.get("paper_status", "OPEN") == "OPEN")]
    if len(live) >= c["max_open"]:
        r.append(f"{len(live)} positions already open (limit {c['max_open']})")
    if any(x["symbol"] == i["symbol"] for x in live):
        r.append("already holding or working an order in this instrument")
    if st["day"]["trades"] >= c["max_trades"]:
        r.append(f"{st['day']['trades']} trades already sent today (limit {c['max_trades']})")
    if st.get("halted"):
        r.append("trading halted: " + st["halted"])
    if qty >= 1 and tg and e > 0:
        gross, cost = abs(tg - e) * qty, round_trip_cost(e, tg, qty, side)
        if gross < c["min_rc"] * cost:
            r.append(f"charges of about Rs {cost:,.0f} are too large against a Rs {gross:,.0f} target (needs {c['min_rc']:g} times)")
    if m and e > 0 and m.get("upper") and m.get("lower") and not (m["lower"] <= e <= m["upper"]):
        r.append("entry is outside the day's price band")
    if funds is not None and margin is not None and margin > funds:
        r.append(f"margin Rs {margin:,.0f} is more than the Rs {funds:,.0f} available")
    return r, max(qty, 0)


class Gateway:
    def __init__(self, path: Path, client=None, master=None, env: dict | None = None, ip_fn=public_ip):
        self.path, self.client, self.master, self.c, self.ip_fn, self._ip, self._ip_at = Path(path), client, master, cfg(env), ip_fn, None, 0.0
        try:
            self.st = json.loads(self.path.read_text())
        except Exception:
            self.st = {}
        self.st.setdefault("intents", {})
        self.st.setdefault("events", [])
        self.st.setdefault("day", {"day": "", "trades": 0, "pnl": 0.0, "stops": 0})
        self.st.setdefault("broker", {})

    # -------------------------------------------------------------- helpers
    def log(self, now: datetime, text: str) -> None:
        self.st["events"] = ([{"t": now.strftime("%H:%M:%S"), "text": text}] + self.st["events"])[:120]

    def mode(self) -> tuple[str, list[str]]:
        if self.c["mode"] == "live" and time.time() - self._ip_at > 300:
            self._ip, self._ip_at = self.ip_fn(), time.time()
        return resolve_mode(self.c, self._ip)

    def save(self) -> None:
        self.path.write_text(json.dumps(self.st, indent=1))

    def mget(self, symbol: str):
        return self.master.get(symbol) if self.master is not None and len(self.master) else None

    # -------------------------------------------------------------- one cycle
    def process(self, trades: list[dict], stats: list[dict], now: datetime, prices: dict | None = None) -> dict:
        c, st, prices = self.c, self.st, prices or {}
        mode, blockers = self.mode()
        today = now.strftime("%Y-%m-%d")
        if st["day"].get("day") != today:
            st["day"] = {"day": today, "trades": 0, "pnl": 0.0, "stops": 0}
            st.pop("halted", None)
            st["intents"] = {k: v for k, v in st["intents"].items() if v["status"] in OPEN_STATES}
        killed = c["kill"] or (self.path.parent / "KILL").exists()
        st.update(mode=mode, wanted=c["mode"], blockers=blockers, killed=killed, updated_at=now.isoformat(timespec="seconds"),
                  caps={k: c[k] for k in ("max_value", "risk", "max_day_loss", "max_open", "max_trades", "sl_min", "sl_max", "min_rc", "first", "last", "squareoff", "gate", "gate_min", "agents")})
        if mode == "off":
            st["note"] = "The gateway is off."
            self.save()
            return st
        if self.client and c["token"] and now.minute % 5 == 0 and now.second < 20 and st["broker"].get("at") != now.strftime("%H:%M"):
            self.read_broker(now)                                    # read-only: funds and profile, to show the connection is good
        if killed and not st.get("halted"):
            st["halted"] = "kill switch"
        if st["day"]["pnl"] <= -c["max_day_loss"] and not st.get("halted"):
            st["halted"] = f"day loss limit of Rs {c['max_day_loss']:,.0f} reached"
            self.log(now, st["halted"])
        # 1. new intents from the paper desks' intraday equity trades
        for t in trades:
            if t["desk"] == "EQUITY" and t["strategy"] in c["agents"] and t["status"] == "OPEN" and t["day"] == today and t.get("opened") not in NOT_INTRADAY and t.get("symbol") and t["id"] not in st["intents"]:
                self.submit(t, stats, now, mode, blockers)
        # 2. follow what is already out there
        book = None
        if mode == "live" and any(x["status"] in OPEN_STATES for x in st["intents"].values()):
            r = self.client.order_book()
            book = r["data"] if r["ok"] and isinstance(r["data"], list) else None
        by_id = {t["id"]: t for t in trades}
        for iid, it in list(st["intents"].items()):
            pt = by_id.get(iid)
            if it["status"] == "DRY":
                if pt:
                    it["paper_status"], it["paper_pnl"], it["paper_exit"] = pt["status"], pt["pnl_rs"], pt.get("exit")
                    if pt["status"] in ("WIN", "LOSS") and not it.get("counted"):       # a dry-run trade still counts toward the day's loss limit and losing streak
                        it["counted"] = True
                        st["day"]["pnl"] = round(st["day"]["pnl"] + float(pt["pnl_rs"] or 0), 2)
                        st["day"]["stops"] = st["day"]["stops"] + 1 if float(pt["pnl_rs"] or 0) < 0 else 0
                        if st["day"]["stops"] >= 3 and not st.get("halted"):
                            st["halted"] = "3 losing trades in a row"
            elif it["status"] in OPEN_STATES and mode == "live" and book is not None:
                self.follow(it, book, now, prices)
        self.save()
        return st

    def read_broker(self, now: datetime) -> None:
        pr, fd = self.client.profile(), self.client.funds()
        b = {"at": now.strftime("%H:%M"), "ok": bool(pr["ok"] and fd["ok"]), "error": None if (pr["ok"] and fd["ok"]) else (pr["error"] or fd["error"])}
        if pr["ok"]:
            b.update(user=(pr["data"] or {}).get("first_name"), nse_ok=(pr["data"] or {}).get("is_nse_onboarded"))
        if fd["ok"]:
            d = fd["data"] or {}
            b.update(funds=(d.get("detailed_avl_balance") or {}).get("eq_mis"), realized=d.get("realized_pnl"), unrealized=d.get("unrealized_pnl"))
        self.st["broker"] = b

    # -------------------------------------------------------------- an intent arrives
    def submit(self, t: dict, stats: list[dict], now: datetime, mode: str, blockers: list[str]) -> dict:
        c, st = self.c, self.st
        i = {"id": t["id"], "agent": t["strategy"], "symbol": t["symbol"], "label": t["label"], "side": "SELL" if t["side"] == "SHORT" else "BUY", "qty": int(float(t["qty"] or 0)), "entry": float(t["entry"] or 0),
             "stop": float(t.get("stop") or 0), "target": float(t.get("target_px") or 0) or None, "created": now.strftime("%H:%M:%S"), "day": t["day"], "hold_min": t.get("hold_min")}
        m = self.mget(i["symbol"])
        funds = margin = None
        if self.client and c["token"] and m and i["qty"] >= 1 and i["entry"] > 0:
            r = self.client.margin(m["id"], i["side"], i["qty"], i["entry"])
            if r["ok"]:
                margin = float((r["data"] or {}).get("total_margin") or 0)
            funds = (st["broker"] or {}).get("funds")
        reasons, qty = check(i, st, c, now, m, self.master is not None and len(self.master) > 0, funds, margin)
        i.update(qty_sent=qty, reasons=reasons, margin=margin, est_cost=round_trip_cost(i["entry"], i["target"] or i["entry"], qty, i["side"]) if qty else None)
        if not reasons:
            p = smart_payload(i, qty, m or {"tick": 0.05, "id": ""}, c)
            bad = validate_smart(p, (m or {}).get("tick") or 0.05) if m else []
            if bad:
                i["reasons"] = bad
            else:
                i["payload"] = p
        if i["reasons"]:
            i["status"] = "REJECTED"
            self.log(now, f"REJECTED {i['label']}: {i['reasons'][0]}")
        else:
            ok, why = gate_ok(i["agent"], stats, c)
            i["gate"] = {"ok": ok, "why": why}
            if mode != "live":
                i["status"] = "DRY"
                i["note"] = "would be sent" if ok else "would be held back: " + why
                st["day"]["trades"] += 1
                self.log(now, f"DRY {i['side']} {qty} {i['symbol']} stop {i['payload']['sl_trigger_price']} ({'gate open' if ok else 'gate closed'})")
            elif not ok:
                i["status"] = "HELD"
                i["note"] = "live gate: " + why
                self.log(now, f"HELD {i['label']}: {why}")
            elif st.get("halted"):
                i["status"] = "HELD"
                i["note"] = st["halted"]
            else:
                self.send(i, now)
        st["intents"][i["id"]] = i
        return i

    # -------------------------------------------------------------- live: send, follow, exit
    def send(self, i: dict, now: datetime) -> None:
        r = self.client.smart_order(i["payload"])
        st = self.st
        st["day"]["trades"] += 1
        data = ((r["data"] or {}).get("order_data") or [{}])[0] if r["ok"] else {}
        if r["ok"] and data.get("order_id") and data.get("order_status") != "FAILED":
            i.update(status="SENT", order_id=data["order_id"], child_id=(data.get("child_order_details") or {}).get("order_id"), sent_at=time.time(), sent=now.strftime("%H:%M:%S"))
            self.log(now, f"SENT {i['side']} {i['qty_sent']} {i['symbol']} {data['order_id']} with stop-loss {i['payload']['sl_trigger_price']}")
        else:
            i.update(status="FAILED", note=(data.get("reason") or r["error"] or "the broker refused the order"))
            self.log(now, f"FAILED {i['label']}: {i['note']}")

    def rows(self, it: dict, book: list[dict]) -> list[dict]:
        return [r for r in book if str(r.get("remarks") or "").startswith(it["id"]) or r.get("id") in (it.get("order_id"), it.get("child_id"))]

    def follow(self, it: dict, book: list[dict], now: datetime, prices: dict) -> None:
        c, rows = self.c, self.rows(it, book)
        parent = next((r for r in rows if r.get("id") == it.get("order_id")), None)
        if not parent:
            if time.time() - it.get("sent_at", time.time()) > c["parent_timeout"] * 3:
                it.update(status="NOFILL", note="the order never appeared in the order book")
            return
        buy = it["side"] == "BUY"
        entry_q = int(float(parent.get("traded_qty") or 0))
        exits = [r for r in rows if r is not parent and r.get("txn_type") == ("SELL" if buy else "BUY") and int(float(r.get("traded_qty") or 0)) > 0]
        exit_q = sum(int(float(r["traded_qty"])) for r in exits)
        net = entry_q - exit_q
        age = time.time() - it.get("sent_at", time.time())
        hhmm = now.strftime("%H:%M")
        child = next((r for r in rows if r.get("parent_order_id") == it.get("order_id") or r.get("id") == it.get("child_id")), None)
        if child and not it.get("child_id"):
            it["child_id"] = child.get("id")
        if it["status"] == "SENT":
            if parent.get("status") == "SUCCESS" or entry_q >= it["qty_sent"]:
                it.update(status="FILLED", entry_fill=float(parent.get("traded_price") or it["entry"]), filled_at=time.time())
                self.log(now, f"FILLED {it['label']} at {it['entry_fill']}")
            elif is_dead(parent.get("status")):
                it["status"] = "FILLED" if entry_q > 0 else "NOFILL"
                if entry_q > 0:
                    it.update(entry_fill=float(parent.get("traded_price") or it["entry"]), filled_at=time.time())
            elif age > c["parent_timeout"]:
                self.cancel_entry(it)
                self.log(now, f"CANCEL {it['label']}: entry not filled in {c['parent_timeout']:.0f} s")
        if it["status"] == "CANCELLING":
            if parent.get("status") == "SUCCESS" or is_dead(parent.get("status")):
                if entry_q > 0:                                    # filled (all or part) before the cancel landed: it is a position now and needs its stop-loss confirmed
                    it.update(status="FILLED", entry_fill=float(parent.get("traded_price") or it["entry"]), filled_at=time.time())
                else:
                    it["status"] = "NOFILL"
            elif time.time() - it.get("cancel_at", 0) > 15:
                self.cancel_entry(it)
        if it["status"] == "FILLED":
            if child and not is_dead(child.get("status")):
                it["status"] = "PROTECTED"
                self.log(now, f"PROTECTED {it['label']}: stop-loss leg {it.get('child_id')} is live")
            elif time.time() - it.get("filled_at", time.time()) > c["prot_wait"]:
                self.flatten(it, net, now, "stop-loss leg is missing")
        if it["status"] == "PROTECTED":
            last = prices.get(it["symbol"])
            hold = it.get("hold_min")
            if net <= 0:
                self.close_out(it, exits, now)
            elif hhmm >= c["squareoff"]:
                self.flatten(it, net, now, "end of day")
            elif hold and time.time() - it.get("filled_at", time.time()) > float(hold) * 60:
                self.flatten(it, net, now, "time stop")
            elif last and ((buy and last < it["payload"]["sl_limit_price"]) or (not buy and last > it["payload"]["sl_limit_price"])):
                self.flatten(it, net, now, "price gapped through the stop-loss limit")
        if it["status"] == "EXITING":
            if net <= 0:
                self.close_out(it, exits, now)
            elif time.time() - it.get("exit_at", 0) > 15 and it.get("exit_tries", 0) < 3:
                self.flatten(it, net, now, it.get("exit_why", "retry"))

    def cancel_entry(self, it: dict) -> None:
        self.client.cancel(it["order_id"], smart=str(it["order_id"]).startswith("GTT-"))
        if it.get("child_id"):
            self.client.cancel(it["child_id"], smart=True)
        it.update(status="CANCELLING", cancel_at=time.time())

    def flatten(self, it: dict, net: int, now: datetime, why: str) -> None:
        """Cancel the broker-side legs, then exit the open quantity at the market."""
        if net <= 0:
            return
        if it.get("child_id"):
            self.client.cancel(it["child_id"], smart=True)
        side = "SELL" if it["side"] == "BUY" else "BUY"
        m = self.mget(it["symbol"]) or {}
        r = self.client.order({"txn_type": side, "exchange": "NSE", "segment": "EQUITY", "product": "INTRADAY", "order_type": "MARKET", "validity": "DAY", "security_id": str(m.get("id") or it["payload"]["security_id"]),
                               "qty": int(net), "remarks": (it["id"] + "-x")[:100]})
        it.update(status="EXITING", exit_why=why, exit_at=time.time(), exit_tries=it.get("exit_tries", 0) + 1)
        self.log(now, f"EXIT {it['label']} ({why}): {'sent' if r['ok'] else 'FAILED ' + str(r['error'])}")

    def close_out(self, it: dict, exits: list[dict], now: datetime) -> None:
        q = sum(int(float(r["traded_qty"])) for r in exits) or it["qty_sent"]
        px = sum(float(r.get("traded_price") or 0) * int(float(r["traded_qty"])) for r in exits) / q if exits else it["entry"]
        d = 1 if it["side"] == "BUY" else -1
        e = it.get("entry_fill") or it["entry"]
        gross = d * (px - e) * q
        cost = round_trip_cost(e, px, q, it["side"])
        it.update(status="EXITED", exit_px=round(px, 2), pnl=round(gross - cost, 2), gross=round(gross, 2), cost=cost, closed=now.strftime("%H:%M:%S"))
        self.st["day"]["pnl"] = round(self.st["day"]["pnl"] + it["pnl"], 2)
        self.st["day"]["stops"] = self.st["day"]["stops"] + 1 if it["pnl"] < 0 else 0
        self.log(now, f"EXITED {it['label']} at {it['exit_px']}: {it['pnl']:+,.0f} after charges")
        if self.st["day"]["stops"] >= 3 and not self.st.get("halted"):
            self.st["halted"] = "3 losing trades in a row"
            self.log(now, "HALTED: 3 losing trades in a row")
