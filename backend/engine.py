"""The paper desk, running with no page open: equities, NIFTY F&O, MCX commodities and crypto, as one team.

Each GitHub run loops for LOOP_SECONDS, re-reading real-time Upstox prices every 15 seconds (all ~2,760 NSE
equities, index options, MCX futures) and Kraken for crypto, and lets every desk open, mark and close its own paper
trades by fixed rules. Every trade lands in one shared list (docs/data/all_trades.json) with the reason it was
taken, so the page, the scoreboard and the learning loop all read the same trades. No order is ever placed.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desks as D        # noqa: E402
import intraday as I     # noqa: E402
import upstox as U       # noqa: E402
import open_fill as OF   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS = Path(os.environ.get("DESK_DOCS") or ROOT / "docs" / "data")
IST = D.IST
IDX = {"nifty": "NSE_INDEX|Nifty 50", "banknifty": "NSE_INDEX|Nifty Bank", "vix": "NSE_INDEX|India VIX"}
NIFTY = IDX["nifty"]


def load(name: str, default):
    f = DOCS / name
    try:
        return json.loads(f.read_text()) if f.exists() else default
    except Exception:
        return default


def save(name: str, obj) -> None:
    (DOCS / name).write_text(json.dumps(obj, indent=1))


def unify_equity(book: dict) -> list[dict]:
    out = []
    for t in book.get("trades", []):
        d = 1 if t["side"] == "LONG" else -1
        pnl = t["pnl_rs"] if t["status"] != "OPEN" else round(d * (t["last"] - t["entry"]) * t["qty"], 2)
        out.append({"id": f"E{str(t['day']).replace('-', '')[2:]}-{t['id']}", "desk": "EQUITY", "strategy": t.get("basis", "price only").replace(" ", "_"), "label": t["label"], "side": t["side"],
                    "entry": t["entry"], "last": t["last"], "exit": t.get("exit", ""), "qty": t["qty"], "stop": t.get("stop"), "status": t["status"], "pnl_rs": pnl, "reason": t.get("reason", ""),
                    "why": t.get("why", ""), "day": t["day"], "opened": t["time"], "closed": "", "risk_class": "Intraday momentum", "margin_rs": round(t["entry"] * t["qty"] * 0.2)})
    return out


def OF_opens(token: str, led: list[dict]) -> dict:
    want = {r["symbol"] for r in led if r["status"] == "PENDING" and r["market"] == "NSE"}
    keys = {x["trading_symbol"]: x["instrument_key"] for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ" and x["trading_symbol"] in want}
    q = U.quotes(list(keys.values()), token)
    return {s: float((q.get(k, {}).get("ohlc") or {}).get("open") or 0) or None for s, k in keys.items()}


def sessions(now: datetime) -> dict:
    t, wk = D.mins(now.strftime("%H:%M")), now.weekday() < 5
    return {"equity": wk and D.mins("09:10") <= t <= D.mins("15:40"), "fno": wk and D.mins("09:15") <= t <= D.mins("15:30"),
            "mcx": wk and D.mins("09:00") <= t <= D.mins("23:30"), "crypto": True}


def close_stale(eq: dict, xb: dict, today: str) -> None:
    """A trade left open from an earlier day (a run was missed) is closed now at its last known price."""
    now = datetime.now(IST)
    for t in eq.get("trades", []):
        if t["status"] == "OPEN" and t["day"] != today:
            I.close_trade(t, t["last"], "carried over: closed late at the last price")
    for t in xb["trades"]:
        if t["status"] == "OPEN" and t["day"] != today and t["desk"] in ("FNO", "COMMODITY"):
            D.finish(t, t["last"], "carried over: closed late at the last price", now, t["pnl_rs"])


def run() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("UPSTOX_TOKEN", "").strip()
    end = time.time() + int(os.environ.get("LOOP_SECONDS", "0"))
    eq = load("live_book.json", {"day": "", "trades": [], "seen": {}, "seq": 0})
    xb = load("desk_book.json", D.new_book())
    archive = {t["id"]: t for t in load("trade_archive.json", [])}
    paused = {s["strategy"] for s in load("strategy_stats.json", []) if s["verdict"] == "PAUSED"}
    news, status, i = I.filings_news(), {"desks": {}}, 0
    mcx_c: list = []
    filled = False
    while True:
        now = datetime.now(IST)
        today, hhmm, ses = now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), sessions(now)
        close_stale(eq, xb, today)
        for t in unify_equity(eq) + xb["trades"]:       # keep every closed trade before the day's book resets
            if t["status"] != "OPEN":
                archive[t["id"]] = t
        info = status["desks"]
        q_idx, ctx = {}, {}
        if token and (ses["fno"] or ses["mcx"] or ses["equity"]):
            try:
                q_idx = U.quotes(list(IDX.values()), token)
            except Exception as e:
                info["indices"] = f"error: {e}"
        if token and ses["equity"]:
            try:
                rows = U.equity_rows(token)
                if rows:
                    I.step(eq, today, hhmm, rows, news)
                info["equity"] = f"{len(rows)} stocks, real time"
            except Exception as e:
                info["equity"] = f"error: {e}"
        elif ses["equity"]:
            info["equity"] = "no token: Yahoo fallback runs in intraday.py"
        if token and ses["equity"] and hhmm >= "09:16" and not filled:
            try:                                   # pending paper orders fill at today's real open, not a day late
                lf, rf = DOCS / "paper_ledger.json", ROOT / "dashboard" / "data" / "desk_rules.json"
                if lf.exists() and rf.exists():
                    led = json.loads(lf.read_text())
                    n = OF.fill_pending(led, json.loads(rf.read_text()), OF_opens(token, led), now.date(), (q_idx.get("NSE_INDEX|India VIX") or {}).get("last_price"))
                    if n:
                        lf.write_text(json.dumps(led, indent=1))
                    info["paper_orders"] = f"{n} pending orders filled or expired at today's open"
                filled = True
            except Exception as e:
                info["paper_orders"] = f"error: {e}"
        if token and ses["mcx"]:
            try:
                mcx_c = mcx_c or D.mcx_contracts(U.instruments("MCX"), now.date())
                D.mcx_step(xb, now, U.quotes([c["key"] for c in mcx_c], token), mcx_c, paused)
                info["commodities"] = f"{len(mcx_c)} MCX futures, real time"
            except Exception as e:
                info["commodities"] = f"error: {e}"
        if token and ses["fno"]:
            try:
                n = q_idx.get(NIFTY, {})
                spot = n.get("last_price")
                exps = [e for e in U.expiries(token, NIFTY) if e >= today]
                open_exp = {t["expiry"] for t in xb["trades"] if t["desk"] == "FNO" and t["status"] == "OPEN"}
                chains = {e: U.option_chain(token, NIFTY, e) for e in sorted(open_exp | {exps[0]}) if e >= today or e in open_exp}
                ctx = {"spot": spot, "prev": (spot - n["net_change"]) if spot and n.get("net_change") is not None else None, "chains": chains, "expiry": exps[0], "lot": U.lot_size(NIFTY, exps[0])}
                D.fno_step(xb, now, ctx, paused)
                info["fno"] = f"NIFTY {spot} , expiry {exps[0]}, {len(chains)} chain(s), real time"
            except Exception as e:
                info["fno"] = f"error: {e}"
        try:
            D.crypto_step(xb, now, D.kraken_ticks(), paused)
            info["crypto"] = "6 coins from Kraken, real time"
        except Exception as e:
            info["crypto"] = f"error: {e}"
        # one shared list of trades
        trades = unify_equity(eq) + xb["trades"]
        for t in trades:
            if t["status"] != "OPEN":
                archive[t["id"]] = t
        status.update(updated_at=now.isoformat(timespec="seconds"), updated_hm=now.strftime("%d %b %H:%M:%S"), loops=i + 1, sessions=ses,
                      note="Real-time Upstox prices for equities, NIFTY options and MCX; Kraken for crypto. Paper trades only." if token else "No Upstox token: delayed fallback prices.")
        i += 1
        if time.time() + 15 >= end:
            break
        time.sleep(15)
    save("live_book.json", eq)
    xb["trades"] = [t for t in xb["trades"] if t["status"] == "OPEN" or t["id"] not in archive]
    save("desk_book.json", xb)
    allt = list(archive.values()) + [t for t in unify_equity(eq) + xb["trades"] if t["status"] == "OPEN"]
    allt.sort(key=lambda t: (t["day"], t["opened"]), reverse=True)
    save("trade_archive.json", sorted((t for t in archive.values()), key=lambda t: (t["day"], t["opened"]))[-4000:])
    save("all_trades.json", allt[:3000])
    stats = D.learn(list(archive.values()))
    save("strategy_stats.json", stats)
    status["open"] = sum(t["status"] == "OPEN" for t in allt)
    save("live_status.json", status)
    print(status["updated_hm"], status["desks"], "open", status["open"], "closed", len(archive))


if __name__ == "__main__":
    run()
