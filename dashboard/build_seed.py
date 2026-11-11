"""Builds the data files the CEO Trading Desk dashboard displays.

Reads the desk's own outputs (reports/*_agents.json, reports/*.json, the backtest result
files) and writes dashboard/data/*.json. Nothing is invented: every row comes from a run, a
backtest, a filing alert, or a number the CEO gave (trading cash).

Usage: python dashboard/build_seed.py [YYYY-MM-DD]     (default: newest agents file)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "data"
IST = timezone(timedelta(hours=5, minutes=30))

# The CEO's own numbers.
TRADING_CASH = 32000
PAPER_START = 32000

AGENTS = {  # id -> (display name, role, tone colour key)
    "DATA": ("Scout", "Data agent"), "TECH": ("Chartist", "Technical analyst"),
    "FUND": ("Ledgerhand", "Fundamentals analyst"), "SENT": ("Pulse", "News and sentiment"),
    "CALL": ("Echo", "Earnings-call analyst"), "BULL": ("Bull", "Bull researcher"),
    "BEAR": ("Bear", "Bear researcher"), "RISK": ("Warden", "Risk manager"),
    "PM": ("Chief", "Portfolio manager"), "LEDGER": ("Scribe", "Ledger agent"),
}


def plain(text: str) -> str:
    t = re.sub(r"\*\*(.*?)\*\*", r"\1", text or "")
    t = re.sub(r"^\s*[-*]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip()


def sym(t: str | None) -> str:
    return (t or "").replace(".NS", "")


def agent_feed(room: dict, rec: dict, stats: dict) -> list[dict]:
    rows: list[dict] = []
    run = room["run_date"]

    def add(agent, text, tone="info", ticker=None, kind="analysis"):
        rows.append({"seq": len(rows) + 1, "run_date": run, "agent": agent,
                     "name": AGENTS[agent][0], "role": AGENTS[agent][1], "tone": tone,
                     "ticker": sym(ticker), "kind": kind, "text": plain(text)})

    cands = room["candidates"]
    top = next((c for c in cands if c["ticker"] == room.get("ticker")), cands[0] if cands else None)
    unverified = "; ".join(room.get("unverified", [])) or "none"
    add("DATA", f"Good evening, CEO. I screened the NSE list with the tested strategies and passed "
                f"{len(cands)} names to the team. Prices are end-of-day from Yahoo Finance. "
                f"Data Unverified today: {unverified}.", "info", kind="briefing")
    if top:
        t = top["ticker"]
        for key, agent in (("technical", "TECH"), ("fundamentals", "FUND"),
                           ("sentiment", "SENT"), ("concall", "CALL")):
            a = top["analysts"].get(key)
            if a and a.get("summary"):
                add(agent, a["summary"], {"bullish": "bull", "bearish": "bear"}.get(a.get("signal"), "neutral"), t)
        add("BULL", top["bull"], "bull", t, "debate")
        add("BEAR", top["bear"], "bear", t, "debate")
    for c in cands:
        if top and c["ticker"] == top["ticker"]:
            continue
        a = c["analysts"].get("technical", {})
        add("TECH", f"Also on the screen: {sym(c['ticker'])}. {a.get('summary', '')}",
            {"bullish": "bull", "bearish": "bear"}.get(a.get("signal"), "neutral"), c["ticker"], "screened")
    notes = " ".join(n for n in room.get("risk_notes", []) if "removed" not in n)
    add("RISK", notes or "No risk flags.", "warn", room.get("ticker"), "risk")
    add("PM", room.get("pm_rationale", ""), "bull" if room.get("decision") == "BUY" else "neutral",
        room.get("ticker"), "decision")
    closed = stats.get("closed_trades", 0)
    add("LEDGER", f"Paper desk record: {closed} closed trades so far. Real money stays off until the "
                  f"gate is met: 100 or more paper trades and 98% confidence after correction.",
        "info", kind="ledger")
    if room.get("decision") == "BUY":
        add("PM", f"CEO, your call. The ticket for {sym(room['ticker'])} is ready on the Morning "
                  f"briefing tab. I will not place anything. You decide.", "bull", room["ticker"], "ask")
    return rows


def plan_rows(room: dict, rec: dict) -> list[dict]:
    rows = []

    def add(symbol, kind, headline, why, source):
        rows.append({"rank": len(rows) + 1, "symbol": symbol, "kind": kind,
                     "headline": headline, "why": why, "source": source})

    if rec.get("action") == "BUY":
        s = sym(rec["ticker"])
        add(s, "Algo signal", f"{rec['strategy']}: entry near {rec['entry_price']}, "
            f"stop {rec['stop_loss']}, target {rec['target']}",
            plain(rec["rationale"]), f"Agent run {rec['run_date']}")
    for c in room["candidates"]:
        if c["ticker"] == room.get("ticker"):
            continue
        a = c["analysts"].get("technical", {})
        add(sym(c["ticker"]), "Screened", "Passed the breakout screen; not chosen today",
            plain(a.get("summary", "")), f"Agent run {room['run_date']}")
    events = json.loads((ROOT / "dashboard" / "inputs" / "events.json").read_text())
    for e in events:
        add(e["symbol"], e["kind"], e["headline"], e["why"], e["source"])
    return rows


def next_results(symbols: list[str]) -> dict[str, str]:
    """Upcoming results date per symbol from Yahoo (projected dates; verify before relying)."""
    out = {}
    try:
        import yfinance as yf
        today = datetime.now(IST).date()
        for s in symbols:
            try:
                d = yf.Ticker(f"{s}.NS").get_earnings_dates(limit=6)
                fut = sorted(x.date() for x in d.index if x.date() >= today)
                if fut:
                    out[s] = fut[0].isoformat()
            except Exception:
                continue
    except Exception:
        pass
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reports = ROOT / "reports"
    files = sorted(reports.glob("*_agents.json"))
    dates = [x for x in sys.argv[1:] if not x.startswith("--")]
    if dates:
        files = [reports / f"{dates[0]}_agents.json"]
    room = json.loads(files[-1].read_text())
    rec = json.loads((reports / f"{room['run_date']}.json").read_text())
    stats = {"closed_trades": 0}

    feed = agent_feed(room, rec, stats)
    plan = plan_rows(room, rec)
    nr = next_results([r["symbol"] for r in plan])
    for r in plan:
        r["next_results"] = nr.get(r["symbol"], "")
    (OUT / "agent_feed.json").write_text(json.dumps(feed, indent=1))
    (OUT / "plan_today.json").write_text(json.dumps(plan, indent=1))

    (OUT / "alerts_log.json").write_text((ROOT / "dashboard" / "inputs" / "alerts.json").read_text())

    # Equity strategies: lab verdicts plus the confidence analysis.
    lab = json.loads((ROOT / "backtest" / "approved_strategies.json").read_text())
    conf = json.loads((ROOT / "backtest" / "confidence_results.json").read_text())
    eq = []
    for name, v in lab["strategies"].items():
        c = conf.get(name, {})
        eq.append({"strategy": name, "market": "NSE stocks", "description": v.get("description", ""),
                   "status": v["status"], "trades": v["trades"], "win_rate": v.get("win_rate", 0),
                   "avg_R": v.get("avg_R", 0), "t_stat": v.get("t_stat", 0),
                   "conf_naive": c.get("confidence_naive", 0), "conf_cluster": c.get("confidence_cluster", 0),
                   "conf_adjusted": c.get("confidence_adjusted", 0), "cagr": v["cagr"], "max_dd": v["max_dd"],
                   "avgR_first": v.get("avg_R_first_60pct", 0), "avgR_last": v.get("avg_R_last_40pct", 0),
                   "why_not_approved": "; ".join(v.get("failed_criteria", []))})
    (OUT / "strategies_eq.json").write_text(json.dumps(eq, indent=1))

    macro = json.loads((ROOT / "backtest" / "macro_lab_results.json").read_text())
    desc = {"donchian_20_10": "Buy a close above the 20-day high, exit below the 10-day low",
            "golden_cross": "Buy when the 50-day average crosses above the 200-day",
            "momentum_12_1": "Buy positive 12-month momentum above the 100-day average"}
    ms = []
    for key, v in macro["strategies"].items():
        strat, kind = key.split(":")
        ms.append({"strategy": strat, "market": kind, "description": desc[strat], "status": v["status"],
                   "trades": v["trades"], "win_rate": v.get("win_rate", 0), "avg_R": v.get("avg_R", 0),
                   "t_stat": v.get("t_stat", 0), "conf_cluster": v.get("conf_cluster", 0),
                   "conf_adjusted": v.get("conf_adjusted", 0), "avgR_first": v.get("avg_R_first_half", 0),
                   "avgR_last": v.get("avg_R_second_half", 0)})
    (OUT / "strategies_macro.json").write_text(json.dumps(ms, indent=1))
    sig = []
    for s in macro["signals"]:
        if s["strategy"] != "donchian_20_10":
            continue
        sig.append({"symbol": s["symbol"], "name": s["name"], "market": s["kind"],
                    "entry_signal_today": "YES" if s["entry_signal_today"] else "no",
                    "last_close": s["last_close"], "atr20": s["atr20"], "last_date": s["last_date"],
                    "buy_hold_pa": macro["buy_and_hold"][s["symbol"]]})
    (OUT / "macro_signals.json").write_text(json.dumps(sig, indent=1))

    # The paper account: starts at the CEO's trading cash. The first row is a pending order.
    entry, stop, target = rec["entry_price"], rec["stop_loss"], rec["target"]
    risk_rs = round(PAPER_START * 0.005, 2)                    # Caution regime: 0.5% of equity
    qty = int(risk_rs // (entry - stop)) if rec.get("action") == "BUY" else 0
    ledger = [{"id": 1, "market": "NSE", "symbol": sym(rec.get("ticker")), "strategy": (rec.get("strategy") or "").split(" (")[0],
               "signal_date": rec["run_date"], "signal_close": entry, "atr": "",
               "status": "PENDING", "opened": "", "closed": "", "entry": entry, "stop": stop,
               "target": target, "qty": qty, "risk_rs": round(qty * (entry - stop), 2),
               "exit": "", "pnl_rs": 0, "r_mult": 0,
               "note": f"Signal from {rec['run_date']} close. Fills at the next open if the gap is within 3%."}
              ] if rec.get("action") == "BUY" else []
    if "--skip-paper" not in sys.argv:       # the daily refresh writes these from the engine
        (OUT / "paper_ledger.json").write_text(json.dumps(ledger, indent=1))
        (OUT / "paper_equity.json").write_text(json.dumps(
            [{"date": rec["run_date"], "equity": PAPER_START}], indent=1))
    rules = [
        {"key": "trading_cash", "label": "Trading cash (CEO)", "value": TRADING_CASH, "unit": "rupees"},
        {"key": "paper_start", "label": "Paper account start", "value": PAPER_START, "unit": "rupees"},
        {"key": "risk_normal", "label": "Risk per trade, normal market", "value": 1.0, "unit": "% of equity"},
        {"key": "risk_caution", "label": "Risk per trade, caution market (VIX 16 to 20)", "value": 0.5, "unit": "% of equity"},
        {"key": "gate_conf", "label": "Confidence needed for real money", "value": 98, "unit": "%"},
        {"key": "gate_trades", "label": "Paper trades needed", "value": 100, "unit": "trades"},
        {"key": "gate_dd", "label": "Largest paper drawdown allowed", "value": 20, "unit": "%"},
        {"key": "stop_pct", "label": "Stop under entry (stocks)", "value": 5, "unit": "%"},
        {"key": "target_pct", "label": "Target over entry (stocks)", "value": 20, "unit": "%"},
    ]
    (OUT / "desk_rules.json").write_text(json.dumps(rules, indent=1))
    print("wrote", sorted(p.name for p in OUT.glob("*.json")))


if __name__ == "__main__":
    main()
