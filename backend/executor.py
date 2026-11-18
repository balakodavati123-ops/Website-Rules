"""The bridge from the paper desks to the broker. OFF unless you switch it on; practice orders first.

Modes (EXEC_MODE): off (default: nothing is sent) | sandbox (Upstox's practice exchange, no money) | live (real orders).
Live needs, all at once: EXEC_MODE=live, EXEC_LIVE_CONFIRM=I-UNDERSTAND-REAL-MONEY, the strategy's verdict to be
READY FOR REVIEW (100+ closed paper trades, 98% confidence), no kill-switch file, and an IP address registered with Upstox.

What it does: when a desk opens an equity or NIFTY option trade on paper, it sends the same trade to the broker as limit
orders priced a hair through the market; when the desk closes the paper trade, it sends the closing orders. Every order carries
a tag built from the trade id, so a trade can never be sent twice. Hard limits: a rupee cap per order, a cap on loss per day
(stops new entries), and a kill switch (a file named KILL in the data folder, or EXEC_KILL=1). Commodities (Upstox has switched MCX
orders off for API users) and crypto (not offered by Upstox) are never sent. Nothing here moves a stop to the exchange: exits follow
the desk's own rules, checked every few seconds.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = {"sandbox": "https://api-sandbox.upstox.com/v3", "live": "https://api-hft.upstox.com/v3"}
IST = timezone(timedelta(hours=5, minutes=30))
SEND_DESKS = {"EQUITY", "FNO"}
BUFFER = 0.003            # limit price this far through the market, so the order fills instead of resting


def cfg() -> dict:
    mode = os.environ.get("EXEC_MODE", "off").lower()
    return {"mode": mode if mode in ("sandbox", "live") else "off", "token": os.environ.get("UPSTOX_EXEC_TOKEN", "").strip(), "algo": os.environ.get("EXEC_ALGO_NAME", "").strip(),
            "max_order": float(os.environ.get("EXEC_MAX_ORDER_RS") or "5000"), "max_day_loss": float(os.environ.get("EXEC_MAX_DAY_LOSS_RS") or "2000"),
            "live_ok": os.environ.get("EXEC_LIVE_CONFIRM", "") == "I-UNDERSTAND-REAL-MONEY", "kill": os.environ.get("EXEC_KILL", "") == "1"}


def tick_round(px: float, side: str, tick: float = 0.05) -> float:
    """Round toward the market side's worse price (up for a buy, down for a sell) to a whole tick."""
    n = px / tick
    n = -(-n // 1) if side == "BUY" else n // 1
    return round(n * tick, 2)


def http_post(url: str, body: dict, token: str, algo: str = "") -> tuple[int, dict]:
    h = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {token}"}
    if algo:
        h["X-Algo-Name"] = algo
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}


def legs_of(t: dict) -> list[dict]:
    """The orders that make up a paper trade: one for a share trade, one per leg for an option structure (buys first)."""
    if t["desk"] == "EQUITY":
        return [{"key": t.get("instrument_key"), "side": "SELL" if t["side"] == "SHORT" else "BUY", "qty": int(float(t["qty"] or 0)), "px": float(t["entry"] or 0), "exit_px": float(t.get("exit") or t.get("last") or 0), "product": "I" if t.get("opened") not in ("swing", "signal") else "D", "tick": 0.05}]
    legs = [{"key": l.get("key"), "side": "SELL" if l["side"] == "S" else "BUY", "qty": int(t.get("lot") or 0) * int(t.get("qty") or 1), "px": float(l["entry"]), "exit_px": float(l.get("last") or l["entry"]), "product": "I", "tick": 0.05} for l in (t.get("legs") or [])]
    return sorted(legs, key=lambda x: x["side"] != "BUY")


def run(trades: list[dict], stats: list[dict], path: Path, post=http_post, now: datetime | None = None) -> dict:
    """Send what is due. Returns the state saved at `path` (orders, mode, reasons orders were held back)."""
    c, now = cfg(), now or datetime.now(IST)
    st = json.loads(path.read_text()) if path.exists() else {"orders": [], "held": []}
    st.update(mode=c["mode"], updated_at=now.isoformat(timespec="seconds"))
    if c["mode"] == "off" or not c["token"]:
        st["note"] = "Execution is off: the desks trade on paper only." if c["mode"] == "off" else "Execution is on but UPSTOX_EXEC_TOKEN is missing."
        path.write_text(json.dumps(st, indent=1))
        return st
    done = {o["tag"] for o in st["orders"] if o.get("order_id")}
    ready = {s["strategy"] for s in stats if s["verdict"] == "READY FOR REVIEW"}
    killed = c["kill"] or (path.parent / "KILL").exists()
    today = now.strftime("%Y-%m-%d")
    sent_ids = {o["paper_id"] for o in st["orders"] if o.get("order_id") and o["phase"] == "in"}
    day_loss = sum(float(t["pnl_rs"] or 0) for t in trades if t["id"] in sent_ids and t["status"] == "LOSS" and t["day"] == today)
    st["held"] = []

    def send(t: dict, i: int, lg: dict, phase: str) -> None:
        tag = f"{t['id']}-{i}-{phase}"[:40]
        if tag in done:
            return
        px = lg["px"] if phase == "in" else lg["exit_px"]
        side = lg["side"] if phase == "in" else ("SELL" if lg["side"] == "BUY" else "BUY")
        price = tick_round(px * (1 + BUFFER if side == "BUY" else 1 - BUFFER), side, lg["tick"])
        rec = {"tag": tag, "paper_id": t["id"], "label": t["label"], "phase": phase, "side": side, "qty": lg["qty"], "price": price, "mode": c["mode"], "ts": now.isoformat(timespec="seconds")}
        if not lg["key"] or lg["qty"] < 1 or price <= 0:
            st["held"].append({**rec, "why": "missing instrument, quantity or price"})
            return
        if phase == "in" and lg["qty"] * price > c["max_order"] and t["desk"] == "EQUITY":
            st["held"].append({**rec, "why": f"order value over the Rs {c['max_order']:,.0f} cap"})
            return
        code, resp = post(BASE[c["mode"]] + "/order/place", {"quantity": lg["qty"], "product": lg["product"], "validity": "DAY", "price": price, "tag": tag, "instrument_token": lg["key"], "order_type": "LIMIT",
                                                              "transaction_type": side, "disclosed_quantity": 0, "trigger_price": 0, "is_amo": False, "slice": False}, c["token"], c["algo"])
        ids = ((resp or {}).get("data") or {}).get("order_ids") or []
        rec.update(http=code, order_id=ids[0] if ids else None, response=None if ids else resp)
        st["orders"].append(rec)
        if ids:
            done.add(tag)

    for t in trades:
        if t["desk"] not in SEND_DESKS:
            continue
        legs = legs_of(t)
        if t["status"] == "OPEN" and not any(o["paper_id"] == t["id"] for o in st["orders"]):
            gate = None
            if killed:
                gate = "kill switch is on"
            elif c["mode"] == "live" and not (c["live_ok"] and t["strategy"] in ready):
                gate = "live mode needs the strategy to be READY FOR REVIEW and the confirmation set"
            elif day_loss <= -c["max_day_loss"]:
                gate = f"day loss limit of Rs {c['max_day_loss']:,.0f} reached"
            elif t["day"] != today or t.get("opened") in ("swing", "weekly", "signal"):
                gate = "only trades the desks open today are mirrored"
            if gate:
                if t["day"] == today and t.get("opened") not in ("swing", "weekly", "signal"):
                    st["held"].append({"paper_id": t["id"], "label": t["label"], "why": gate})
                continue
            for i, lg in enumerate(legs):
                send(t, i, lg, "in")
        elif t["status"] in ("WIN", "LOSS") and any(o["paper_id"] == t["id"] and o["phase"] == "in" and o.get("order_id") for o in st["orders"]):
            for i, lg in enumerate(legs):
                send(t, i, lg, "out")
    path.write_text(json.dumps(st, indent=1))
    return st
