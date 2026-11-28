"""Real orders on your own Upstox account: never without your approval, never beyond your wallet. OFF unless you switch it on.

Modes (EXEC_MODE): off (default: nothing is sent) | sandbox (Upstox's practice exchange, no money; UPSTOX_SANDBOX_TOKEN) | live
(real orders; UPSTOX_EXEC_TOKEN, plus EXEC_LIVE_CONFIRM=I-UNDERSTAND-REAL-MONEY).

For every trade a desk opens on paper, in this order:
 1. Gates. All must pass or nothing happens, and the reason is shown on the dashboard:
    - the mode is on;
    - you approved the strategy for live trading (CEO APPROVE LIVE <strategy>);
    - its paper record is READY FOR REVIEW, unless you deliberately set EXEC_GATE=ceo with EXEC_GATE_CONFIRM=I-ACCEPT-UNVALIDATED-STRATEGY;
    - the kill switch is off (EXEC_KILL=1 or a file named KILL in the data folder);
    - today's live loss is above -EXEC_MAX_DAY_LOSS_RS;
    - fewer than EXEC_MAX_OPEN live positions are open;
    - the desk opened the trade today.
 2. Size from your wallet. Upstox's funds API gives the cash available. Usable cash is that times EXEC_WALLET_USE (default 0.9), minus what
    other tickets have reserved. Upstox's margin calculator gives the exact cash one lot (or one share) needs, delivery basis, so no
    borrowed money. The live size is the paper size cut to what usable cash pays for, and never above EXEC_MAX_ORDER_RS. If one unit does
    not fit, there is no ticket.
 3. Ticket. The order is written to live_orders.json and pushed to your phone with Approve and Reject links. It waits
    EXEC_APPROVAL_MINUTES (default 5), then expires.
 4. Your approval. Approval is a GitHub issue "CEO APPROVE ORDER <ticket>" opened by you, from the dashboard button or the phone link;
    only the repository owner counts. Without it nothing is sent. Reject or silence: nothing is sent.
 5. Send. First the wallet and the price are checked again: the price may not have moved more than EXEC_MAX_SLIP_PCT (default 1%) against
    the ticket. Then limit orders go out a hair through the market, buy legs first. A spread's sell leg goes only after its buy leg has filled.
 6. Fills. An entry not filled within EXEC_FILL_TIMEOUT_S (default 60 s) is cancelled. The live position is what actually filled.
 7. Exit. When the desk closes the paper trade, the exit orders go at once for the filled quantity, short legs first, with no second
    approval (closing only reduces risk). An exit that does not fill is re-priced up to 3 times, then you get an urgent alert to close it by hand.

Commodities and crypto are never sent. Upstox needs every order to come from your registered static IP (since 1 Apr 2026). A GitHub-hosted
runner has none; run the engine on a self-hosted runner whose IP you registered (README section 3).
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ORDER = {"sandbox": "https://api-sandbox.upstox.com/v3", "live": "https://api-hft.upstox.com/v3"}
API = "https://api.upstox.com/v2"
IST = timezone(timedelta(hours=5, minutes=30))
SEND_DESKS = {"EQUITY", "FNO"}
BUFFER = 0.003            # entry limit price this far through the market, so the order fills instead of resting
EXIT_BUFFERS = (0.005, 0.015, 0.03)
CONFIRM, GATE_CONFIRM = "I-UNDERSTAND-REAL-MONEY", "I-ACCEPT-UNVALIDATED-STRATEGY"
LIVE_STATES = ("APPROVED", "SENDING", "OPEN", "CLOSING")


def cfg(env: dict | None = None) -> dict:
    e = os.environ if env is None else env
    f = lambda k, d: float(e.get(k) or d)
    mode = (e.get("EXEC_MODE") or "off").lower()
    mode = mode if mode in ("sandbox", "live") else "off"
    return {"mode": mode, "token": (e.get("UPSTOX_EXEC_TOKEN") or "").strip(), "sandbox_token": (e.get("UPSTOX_SANDBOX_TOKEN") or "").strip(),
            "algo": (e.get("EXEC_ALGO_NAME") or "").strip(), "live_ok": e.get("EXEC_LIVE_CONFIRM", "") == CONFIRM,
            "gate": "ceo" if (e.get("EXEC_GATE") or "").lower() == "ceo" and e.get("EXEC_GATE_CONFIRM", "") == GATE_CONFIRM else "strict",
            "kill": e.get("EXEC_KILL", "") == "1", "max_order": f("EXEC_MAX_ORDER_RS", 50000), "max_day_loss": f("EXEC_MAX_DAY_LOSS_RS", 2000),
            "max_open": int(f("EXEC_MAX_OPEN", 2)), "wallet_use": min(1.0, max(0.1, f("EXEC_WALLET_USE", 0.9))), "minutes": f("EXEC_APPROVAL_MINUTES", 5),
            "slip": f("EXEC_MAX_SLIP_PCT", 1.0) / 100, "fill_s": f("EXEC_FILL_TIMEOUT_S", 60), "sandbox_wallet": f("EXEC_SANDBOX_WALLET_RS", 100000)}


def tick_round(px: float, side: str, tick: float = 0.05) -> float:
    """Round toward the market side's worse price (up for a buy, down for a sell) to a whole tick."""
    n = px / tick
    n = -(-n // 1) if side == "BUY" else n // 1
    return round(n * tick, 2)


def ticket_id(paper_id: str) -> str:
    return "T" + hashlib.sha1(paper_id.encode()).hexdigest()[:5].upper()


# ---------- the broker, through small functions the tests replace ----------
def http(method: str, url: str, token: str, body: dict | None = None, algo: str = "") -> tuple[int, dict]:
    h = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    if body is not None:
        h["Content-Type"] = "application/json"
    if algo:
        h["X-Algo-Name"] = algo
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:                                               # network: report, never crash the engine
        return 0, {"error": str(e)[:120]}


def funds(token: str, call=http) -> tuple[float | None, str]:
    """Cash available to trade (equity segment), from Upstox's funds API."""
    code, r = call("GET", API + "/user/get-funds-and-margin?segment=SEC", token)
    if code != 200:
        return None, "token expired or not valid" if code in (401, 403) else f"funds not available (HTTP {code})"
    v = ((r.get("data") or {}).get("equity") or {}).get("available_margin")
    return (float(v), "") if v is not None else (None, "funds not in the reply")


def _errors(r: dict) -> str:
    errs = (r or {}).get("errors") or []
    if errs:
        e = errs[0]
        code = e.get("errorCode") or e.get("error_code") or ""
        msg = e.get("message") or ""
        if code == "UDAPI1154":
            msg = "this machine's IP is not your registered static IP (Upstox refuses orders from any other address)"
        return f"{code} {msg}".strip()
    return str((r or {}).get("error") or r)[:160]


# ---------- what a paper trade becomes as orders ----------
def legs_of(t: dict, key_of=None) -> list[dict]:
    """The orders a paper trade is made of, at the paper size. Equity: one leg in shares. Options: one leg per contract, in units."""
    if t["desk"] == "EQUITY":
        key = t.get("instrument_key") or (key_of(t.get("symbol")) if key_of and t.get("symbol") else None)
        return [{"key": key, "name": t.get("symbol") or key, "side": "SELL" if t["side"] == "SHORT" else "BUY", "unit": 1, "units": int(float(t["qty"] or 0)), "px": float(t["entry"] or 0),
                 "now": float(t.get("last") or t["entry"] or 0), "product": "I" if t.get("horizon") in ("scalp", "intraday", None, "") and t.get("opened") not in ("swing", "signal") else "D"}]
    lot = int(t.get("lot") or 0)
    legs = [{"key": l.get("key"), "name": " ".join(str(x) for x in (t.get("underlying") or "NIFTY", int(float(l["strike"])) if l.get("strike") else "", l.get("kind") or "", t.get("expiry") or "") if x),
             "side": "SELL" if l["side"] == "S" else "BUY", "unit": lot, "units": int(t.get("qty") or 1), "px": float(l["entry"]),
             "now": float(l.get("last") or l["entry"]), "product": "D" if t.get("horizon") in ("weekly", "monthly", "swing") else "I"} for l in (t.get("legs") or [])]
    return sorted(legs, key=lambda x: x["side"] != "BUY")


def size(t: dict, legs: list[dict], usable: float, c: dict, margin=None) -> tuple[int, float, str]:
    """How many units (lots or shares) the wallet pays for: (n, rupees for n, note). margin(legs) -> rupees for one unit, or None."""
    want = min(lg["units"] for lg in legs) if legs else 0
    one = margin([(lg["key"], lg["unit"], lg["side"]) for lg in legs]) if margin else None
    if one is None:
        one = sum(lg["px"] * lg["unit"] for lg in legs if lg["side"] == "BUY") or None             # cash basis: what the bought legs cost
    if not one or one <= 0:
        return 0, 0.0, "could not work out the cash one unit needs"
    n = min(want, int(usable // one), int(c["max_order"] // one))
    what = "lot" if t["desk"] == "FNO" else "share"
    if n < 1:
        return 0, round(one), (f"one {what} needs Rs {one:,.0f}; usable wallet is Rs {max(usable, 0):,.0f}" if one > usable else
                               f"one {what} needs Rs {one:,.0f}, over the Rs {c['max_order']:,.0f} cap per order")
    note = "" if n == want else f"cut from {want} to {n} {what}{'s' if n != 1 else ''} to fit your wallet and limits"
    return n, round(one * n), note


# ---------- the desk ----------
def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def approve(path: Path, tid: str, now: datetime, ok: bool = True) -> str:
    """Your decision on a ticket (from the CEO inbox)."""
    st = load(path)
    tk = (st.get("tickets") or {}).get(tid.strip().upper())
    if not tk:
        return f"There is no order ticket {tid}."
    if tk["status"] != "AWAITING":
        return f"Ticket {tk['id']} is already {tk['status'].lower()}: nothing changed."
    if now.isoformat() > tk["expires"]:
        tk["status"], tk["why"] = "EXPIRED", "approval came after the ticket expired"
        path.write_text(json.dumps(st, indent=1))
        return f"Ticket {tk['id']} had expired at {tk['expires'][11:16]}: nothing was sent."
    tk["status"], tk["decided"] = ("APPROVED" if ok else "REJECTED"), now.isoformat(timespec="seconds")
    path.write_text(json.dumps(st, indent=1))
    return (f"Approved {tk['id']}: {tk['label']}, {tk['n']} {tk['unit_name']}, up to Rs {tk['cost']:,.0f}. It goes to Upstox after a last wallet and price check."
            if ok else f"Rejected {tk['id']}: nothing will be sent.")


def step(trades: list[dict], stats: list[dict], live_ok: set, path: Path, now: datetime, deps: dict | None = None) -> dict:
    """Run the desk once. trades: every paper trade (open and closed). stats: the strategies' paper records. live_ok: strategies you
    approved for live. deps (tests replace them): env, call(method, url, token, body, algo), margin(legs), key_of(symbol), push(title, body, ticket, urgent)."""
    d = deps or {}
    c = cfg(d.get("env"))
    call, push = d.get("call", http), d.get("push") or (lambda *a, **k: None)
    st = load(path)
    st.setdefault("tickets", {}), st.setdefault("orders", [])
    today = now.strftime("%Y-%m-%d")
    st.update(mode=c["mode"], updated_at=now.isoformat(timespec="seconds"), gate=c["gate"], live_strategies=sorted(live_ok),
              limits={"max_order": c["max_order"], "max_day_loss": c["max_day_loss"], "max_open": c["max_open"], "wallet_use": c["wallet_use"],
                      "approval_minutes": c["minutes"], "max_slip_pct": round(c["slip"] * 100, 2)})
    st["held"] = [h for h in st.get("held") or [] if h.get("day") == today]
    active = [tk for tk in st["tickets"].values() if tk["status"] in LIVE_STATES]
    blocked = ("Off: the desks trade on paper only. Nothing is sent to your broker." if c["mode"] == "off" else
               "Live was asked for, but EXEC_LIVE_CONFIRM is not the confirmation phrase: no new orders." if c["mode"] == "live" and not c["live_ok"] else
               ("UPSTOX_SANDBOX_TOKEN" if c["mode"] == "sandbox" else "UPSTOX_EXEC_TOKEN") + " is missing: no new orders."
               if not (c["sandbox_token"] if c["mode"] == "sandbox" else c["token"]) else None)
    mode = c["mode"]
    if blocked:
        if not active:
            st["note"] = blocked
            st["summary"] = _summary(st, today)
            path.write_text(json.dumps(st, indent=1))
            return st
        mode = active[0].get("mode") or "live"                       # positions already at the broker: keep managing their exits
        blocked += f" {len(active)} position(s) already at the broker are still managed until they close."
    token = c["sandbox_token"] if mode == "sandbox" else c["token"]
    st["note"] = blocked or ("Practice orders on Upstox's sandbox: no money moves." if mode == "sandbox" else "LIVE: real orders, each one only after your approval.")
    by_id = {t["id"]: t for t in trades}
    killed = c["kill"] or (path.parent / "KILL").exists()

    # the wallet: real cash when the account token works (also in practice mode), else the practice wallet
    def wallet() -> tuple[float | None, str]:
        v, why = funds(c["token"], call) if c["token"] else (None, "no account token")
        if v is None and mode == "sandbox":
            return c["sandbox_wallet"], f"practice wallet (EXEC_SANDBOX_WALLET_RS); {why}"
        return v, why
    w_avail, w_why = wallet()
    reserved = sum(tk["cost"] for tk in st["tickets"].values() if tk["status"] in ("AWAITING", "APPROVED", "SENDING") and tk["day"] == today)
    usable = (w_avail * c["wallet_use"] - reserved) if w_avail is not None else None
    st["wallet"] = {"available": w_avail, "usable": round(usable) if usable is not None else None, "reserved": round(reserved), "note": w_why, "at": now.strftime("%H:%M:%S")}

    def held(t: dict, why: str) -> None:
        if not any(h["paper_id"] == t["id"] and h["why"] == why for h in st["held"]):
            st["held"] = [h for h in st["held"] if h["paper_id"] != t["id"]] + [{"paper_id": t["id"], "label": t["label"], "strategy": t.get("strategy"), "why": why,
                                                                                 "day": today, "at": now.strftime("%H:%M")}]

    def order(tk: dict, lg: dict, side: str, qty: int, price: float, phase: str, attempt: int = 0) -> dict:
        tag = f"{tk['id']}-{lg['i']}-{phase}{attempt or ''}"[:40]
        rec = {"ticket": tk["id"], "paper_id": tk["paper_id"], "label": tk["label"], "leg": lg["i"], "phase": phase, "side": side, "qty": qty, "price": price,
               "tag": tag, "mode": mode, "ts": now.isoformat(timespec="seconds"), "status": "sent", "filled": 0, "avg": None}
        code, r = call("POST", ORDER[mode] + "/order/place", token, {"quantity": qty, "product": lg["product"], "validity": "DAY", "price": price, "tag": tag,
                                                                     "instrument_token": lg["key"], "order_type": "LIMIT", "transaction_type": side,
                                                                     "disclosed_quantity": 0, "trigger_price": 0, "is_amo": False, "slice": True}, c["algo"])
        ids = ((r or {}).get("data") or {}).get("order_ids") or []
        if code == 200 and ids:
            rec.update(order_id=ids[0], order_ids=ids)
            if mode == "sandbox":                                           # the practice exchange reports no fills: count it filled at the limit
                rec.update(status="complete", filled=qty, avg=price, note="practice exchange: assumed filled at the limit price")
        else:
            rec.update(status="failed", why=f"HTTP {code}: {_errors(r)}")
        st["orders"].append(rec)
        return rec

    def sync(rec: dict) -> None:
        """How a sent order stands at Upstox (live only; the practice exchange has no order book API)."""
        if rec["status"] in ("complete", "rejected", "cancelled", "failed") or mode != "live" or not rec.get("order_id"):
            return
        code, r = call("GET", API + "/order/details?order_id=" + urllib.parse.quote(rec["order_id"]), token)
        x = (r or {}).get("data") or {}
        if code == 200 and x:
            s_ = str(x.get("status") or "").lower()
            rec.update(filled=int(x.get("filled_quantity") or 0), avg=float(x.get("average_price") or 0) or None,
                       status="complete" if s_ == "complete" else "rejected" if s_ == "rejected" else "cancelled" if s_ == "cancelled" else
                       "cancel sent" if rec["status"] == "cancel sent" else "open", why=x.get("status_message") or rec.get("why"))

    def cancel(rec: dict) -> None:
        call("DELETE", ORDER[mode] + "/order/cancel?order_id=" + urllib.parse.quote(rec["order_id"]), token, None, c["algo"])
        rec["status"] = "cancel sent"
        sync(rec)

    def stale(rec: dict) -> bool:
        return rec["status"] in ("sent", "open") and (now - datetime.fromisoformat(rec["ts"])).total_seconds() > c["fill_s"]

    def recs(tk: dict, phase: str) -> list[dict]:
        return [o for o in st["orders"] if o["ticket"] == tk["id"] and o["phase"] == phase]

    for o in st["orders"]:
        if o["status"] in ("sent", "open", "cancel sent"):
            sync(o)
    day_pnl = sum(tk.get("pnl") or 0 for tk in st["tickets"].values() if tk.get("closed_day") == today)
    live_open = sum(1 for tk in st["tickets"].values() if tk["status"] in ("AWAITING",) + LIVE_STATES)
    ready = {s_["strategy"] for s_ in stats if s_.get("verdict") == "READY FOR REVIEW"}

    # 1-3: new paper trades become tickets
    for t in ([] if blocked else trades):
        if t["desk"] not in SEND_DESKS or t["status"] != "OPEN" or t.get("day") != today or ticket_id(t["id"]) in st["tickets"]:
            continue
        gate = ("the kill switch is on" if killed else
                f"strategy {t.get('strategy')} is not approved for live (CEO APPROVE LIVE {t.get('strategy')})" if t.get("strategy") not in live_ok else
                "its paper record is not READY FOR REVIEW yet" if c["gate"] == "strict" and t.get("strategy") not in ready else
                f"today's live loss limit of Rs {c['max_day_loss']:,.0f} is reached" if day_pnl <= -c["max_day_loss"] else
                f"{live_open} live positions are open or waiting (limit {c['max_open']})" if live_open >= c["max_open"] else
                f"wallet unknown: {w_why}" if usable is None else
                "multi-day trades are not mirrored" if t.get("opened") in ("swing", "weekly", "signal") else None)
        if gate:
            held(t, gate)
            continue
        legs = legs_of(t, d.get("key_of"))
        if not legs or any(not lg["key"] or lg["px"] <= 0 or lg["units"] < 1 for lg in legs):
            held(t, "missing instrument, quantity or price")
            continue
        n, cost, note = size(t, legs, usable, c, d.get("margin"))
        if n < 1:
            held(t, "wallet: " + note)
            continue
        tid, unit = ticket_id(t["id"]), "lot" if t["desk"] == "FNO" else "share"
        tk = {"id": tid, "paper_id": t["id"], "label": t["label"], "strategy": t.get("strategy"), "desk": t["desk"], "day": today,
              "created": now.isoformat(timespec="seconds"), "expires": (now + timedelta(minutes=c["minutes"])).isoformat(timespec="seconds"),
              "status": "AWAITING", "n": n, "unit_name": unit + ("s" if n != 1 else ""), "paper_n": min(lg["units"] for lg in legs), "cost": cost,
              "wallet_usable": round(usable), "note": note, "mode": mode,
              "legs": [{"i": i, "key": lg["key"], "name": lg.get("name") or lg["key"], "side": lg["side"], "unit": lg["unit"], "qty": n * lg["unit"], "px": round(lg["px"], 2), "product": lg["product"]}
                       for i, lg in enumerate(legs)],
              "stop": t.get("stop") or t.get("stop_u"), "target": t.get("target_px") or t.get("target_u"), "reason": (t.get("reason") or "")[:300]}
        st["tickets"][tid] = tk
        usable -= cost
        live_open += 1
        what = "; ".join(f"{lg['side'].lower()} {lg['qty']} {lg['name']} near {lg['px']}" for lg in tk["legs"])
        push(f"Approve order {tid}? {t['label']}", f"{'PRACTICE' if mode == 'sandbox' else 'REAL MONEY'}: {n} {tk['unit_name']}, up to Rs {cost:,.0f} of your "
             f"Rs {w_avail:,.0f} wallet. {what}. {note + '. ' if note else ''}Expires at {tk['expires'][11:16]}.", tid, False)

    # 4-7: tickets move on
    for tk in st["tickets"].values():
        t = by_id.get(tk["paper_id"])
        closed = not t or t.get("status") in ("WIN", "LOSS", "VOID")
        legs_now = {lg["key"]: lg["now"] for lg in legs_of(t, d.get("key_of"))} if t else {}
        if tk["status"] == "AWAITING":
            if killed or closed or blocked:
                tk["status"], tk["why"] = "CANCELLED", "kill switch" if killed else "the desk closed the trade before you approved" if closed else blocked
            elif now.isoformat() > tk["expires"]:
                tk["status"], tk["why"] = "EXPIRED", "no approval in time: nothing was sent"
        if tk["status"] == "APPROVED":
            moved = [lg for lg in tk["legs"] if lg["side"] == "BUY" and legs_now.get(lg["key"]) and legs_now[lg["key"]] - lg["px"] > c["slip"] * lg["px"]
                     or lg["side"] == "SELL" and tk["desk"] == "EQUITY" and legs_now.get(lg["key"]) and lg["px"] - legs_now[lg["key"]] > c["slip"] * lg["px"]]
            fresh, why_w = wallet()
            if killed or closed or blocked:
                tk["status"], tk["why"] = "CANCELLED", "kill switch" if killed else "the desk closed the trade before it was sent" if closed else blocked
            elif moved:
                tk["status"], tk["why"] = "CANCELLED", f"the price moved more than {c['slip'] * 100:.1f}% against the ticket before sending: nothing sent"
            elif fresh is None or tk["cost"] > fresh * c["wallet_use"]:
                tk["status"], tk["why"] = "CANCELLED", "wallet check before sending failed: " + (why_w or f"Rs {fresh:,.0f} available")
            else:
                tk["status"], tk["sent"] = "SENDING", now.isoformat(timespec="seconds")
                first = [lg for lg in tk["legs"] if lg["side"] == "BUY"] or tk["legs"]              # a short share trade is a single SELL
                for lg in first:
                    px = legs_now.get(lg["key"], lg["px"])
                    r = order(tk, lg, lg["side"], lg["qty"], tick_round(px * (1 + BUFFER if lg["side"] == "BUY" else 1 - BUFFER), lg["side"]), "in")
                    if r["status"] == "failed":
                        tk["why"] = r["why"]
                ins = recs(tk, "in")
                if ins and all(o["status"] == "failed" for o in ins):
                    tk["status"] = "FAILED"
                    push(f"Order {tk['id']} was refused by Upstox", tk["why"], tk["id"], True)
        if tk["status"] == "SENDING":
            for o in recs(tk, "in"):
                if stale(o):
                    cancel(o)
            ins = recs(tk, "in")
            buys = [o for o in ins if o["side"] == "BUY"]
            covers = [lg for lg in tk["legs"] if lg["side"] == "SELL" and buys]
            if covers and all(o["status"] in ("complete", "rejected", "cancelled", "failed") for o in buys) and not any(o["side"] == "SELL" for o in ins):
                ratio = min((o["filled"] / o["qty"]) for o in buys if o["qty"]) if buys else 0
                for lg in covers:                                               # the covering short leg, only once the long leg is in, sized to its fill
                    q = int(lg["qty"] * ratio // lg["unit"]) * lg["unit"]
                    if q > 0:
                        order(tk, lg, "SELL", q, tick_round(legs_now.get(lg["key"], lg["px"]) * (1 - BUFFER), "SELL"), "in")
                ins = recs(tk, "in")
            covered = not covers or any(o["side"] == "SELL" for o in ins) or not any(o["filled"] for o in buys)
            if covered and all(o["status"] in ("complete", "rejected", "cancelled", "failed") for o in ins):
                tk["filled"] = [sum(o["filled"] for o in ins if o["leg"] == lg["i"]) for lg in tk["legs"]]
                if not any(tk["filled"]):
                    tk["status"], tk["why"] = "CANCELLED", tk.get("why") or "not filled in time: cancelled, nothing bought"
                else:
                    tk["status"] = "OPEN"
                    push(f"Filled {tk['id']}: {tk['label']}", "; ".join(f"{o['side'].lower()} {o['filled']} at {o['avg']}" for o in ins if o["filled"]), tk["id"], False)
        if tk["status"] == "OPEN" and closed:
            tk["status"], tk["exit_started"] = "CLOSING", now.isoformat(timespec="seconds")
        if tk["status"] == "CLOSING":
            outs = recs(tk, "out")
            have = lambda i: (tk.get("filled") or [0] * len(tk["legs"]))[i]
            gone = lambda i: sum(o["filled"] for o in outs if o["leg"] == i)
            for lg in sorted(tk["legs"], key=lambda x: x["side"] == "BUY"):             # buy back a short leg before selling the long one
                mine = [o for o in outs if o["leg"] == lg["i"]]
                if mine and stale(mine[-1]):
                    cancel(mine[-1])
                if have(lg["i"]) <= gone(lg["i"]) or any(o["status"] in ("sent", "open", "cancel sent") for o in mine):
                    continue
                if lg["side"] == "BUY" and any(x["side"] == "SELL" and have(x["i"]) > gone(x["i"]) for x in tk["legs"]):
                    continue                                                       # the short leg is still open: wait for it
                tries = len(mine)
                if tries >= len(EXIT_BUFFERS):
                    if not tk.get("alerted"):
                        tk["alerted"] = True
                        push(f"URGENT: close {tk['label']} by hand", f"Exit orders for ticket {tk['id']} did not fill after {tries} tries. Close it in the Upstox app now.", tk["id"], True)
                    continue
                side = "SELL" if lg["side"] == "BUY" else "BUY"
                ref = legs_now.get(lg["key"]) or lg["px"]
                order(tk, lg, side, have(lg["i"]) - gone(lg["i"]), tick_round(ref * (1 - EXIT_BUFFERS[tries] if side == "SELL" else 1 + EXIT_BUFFERS[tries]), side), "out", tries)
                outs = recs(tk, "out")
            if all(gone(lg["i"]) >= have(lg["i"]) for lg in tk["legs"]):
                pnl = sum((o["avg"] or 0) * o["filled"] * (1 if o["side"] == "SELL" else -1) for o in recs(tk, "in") + outs)
                tk.update(status="CLOSED", pnl=round(pnl, 2), closed_day=today, closed=now.isoformat(timespec="seconds"))
                push(f"Closed {tk['id']}: {tk['label']}", f"Result before charges: Rs {pnl:+,.0f}.", tk["id"], False)
    st["orders"] = st["orders"][-400:]
    old = sorted((k for k, v in st["tickets"].items() if v["day"] < today and v["status"] in ("CLOSED", "CANCELLED", "EXPIRED", "REJECTED", "FAILED")),
                 key=lambda k: st["tickets"][k]["created"])
    for k in old[:-200]:
        del st["tickets"][k]
    st["summary"] = _summary(st, today)
    path.write_text(json.dumps(st, indent=1))
    return st


def _summary(st: dict, today: str) -> dict:
    tks = (st.get("tickets") or {}).values()
    return {"awaiting": sum(1 for tk in tks if tk["status"] == "AWAITING"), "open": sum(1 for tk in tks if tk["status"] in LIVE_STATES),
            "today_pnl": round(sum(tk.get("pnl") or 0 for tk in tks if tk.get("closed_day") == today), 2),
            "static_ip_refused": any("static IP" in str(o.get("why")) for o in st.get("orders") or [] if str(o.get("ts", ""))[:10] == today)}
