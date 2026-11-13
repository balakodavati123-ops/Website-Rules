"""Signal desk: a Rs 1,00,000 paper book driven by the research agents' structured hand-off.

Pipeline (the operational rules the CEO set, adapted to daily bars):
  1. SIGNAL   The latest research run's candidates become standardized signals: ticker,
              financial trajectory, sentiment, urgency, rule-based conviction 0-1, drivers
              and red flags. Only conviction >= 0.75 is tradable.
  2. VERIFY   Chart confluence on daily bars before any entry: close above the 9 and 21 EMA
              (trend), volume at least 1.5x its 20-day average, and ADX(14) at least 20 --
              below 20 the market is sideways and the desk does not enter. (The real spec
              uses intraday VWAP; this desk only has end-of-day bars, so the daily close
              and EMAs stand in for it.)
  3. SIZE     One tranche = a third of the book. Everything available only when conviction
              >= 0.90 AND ADX > 25, and the stop is computed before the entry. At most 3
              open positions, one per ticker.
  4. PROTECT  Hard stop 1.5x ATR(14) under entry. At +1.5R the stop moves to breakeven and
              then trails the 9 EMA / 1x ATR. If price gains under 0.5x ATR in 6 sessions,
              the trade is closed as a sideways exit.
  5. LEARN    Every stop-out or sideways exit writes a diagnostic (index divergence,
              pre-entry run-up, stop placement) and a lesson. Mechanical lessons gate the
              next entries: a run-up lesson skips names already up 8%+ in 10 days; an ADX
              lesson caps sizing at one tranche when ADX <= 25.

Paper only, filled at the next open, 0.25% round-trip cost. Usage: python dashboard/signal_desk.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dashboard" / "data"
IST = timezone(timedelta(hours=5, minutes=30))
BOOK, COST, TRANCHES, MAX_OPEN = 100000.0, 0.0025, 3, 3
LED, LES, SIG = DATA / "signal_ledger.json", DATA / "signal_lessons.json", DATA / "desk_signals.json"

TRAJ = [(15, "Exponential_Profit"), (5, "Steady_Growth"), (-5, "Flat"), (-999, "Loss_Widening")]
SENT = {2: "Strong_Positive", 1: "Positive", 0: "Neutral", -1: "Negative", -2: "Strong_Negative"}


def jload(p, default):
    return json.loads(p.read_text()) if p.exists() else default


def make_signals(room: dict) -> list[dict]:
    out = []
    for c in room.get("candidates", []):
        sigs = {k: (v or {}).get("signal", "neutral") for k, v in c.get("analysts", {}).items() if isinstance(v, dict)}
        net = sum(1 for s in sigs.values() if s == "bullish") - sum(1 for s in sigs.values() if s == "bearish")
        m = re.search(r"surprise of (-?[\d.]+)%", str(c.get("bull", "")))
        eps = float(m.group(1)) if m else None
        traj = next(label for cut, label in TRAJ if (eps if eps is not None else {2: 7, 1: 7, 0: 0, -1: -7, -2: -7}[max(-2, min(2, net))]) >= cut)
        conviction = 0.5 + (0.1 if room.get("decision") == "BUY" and c["ticker"] == room.get("ticker") else 0) + 0.05 * net + (0.05 if (eps or 0) >= 5 else 0)
        conviction = round(max(0.0, min(0.95, conviction)), 2)
        out.append({"ticker": c["ticker"], "trajectory": traj, "sentiment": SENT[max(-2, min(2, net))],
                    "urgency": "Short_Term_Swing", "conviction": conviction, "eligible": "yes" if conviction >= 0.75 else "no",
                    "drivers": "; ".join(f"{k} {v}" for k, v in sigs.items()) + (f"; EPS surprise {eps:+.1f}%" if eps is not None else ""),
                    "red_flags": "; ".join(n for n in room.get("risk_notes", []) if "removed" not in n)[:200],
                    "run_date": room.get("run_date", ""), "verdict": "", "note": ""})
    return out


def ind(df):
    c, h, l = df.Close, df.High, df.Low
    ema = lambda n: c.ewm(span=n, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    up, dn = h.diff(), -l.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=c.index).ewm(alpha=1 / 14, adjust=False).mean() / atr * 100
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=c.index).ewm(alpha=1 / 14, adjust=False).mean() / atr * 100
    dx = (plus - minus).abs() / (plus + minus).replace(0, np.nan) * 100
    return {"e9": ema(9), "e21": ema(21), "atr": atr, "adx": dx.ewm(alpha=1 / 14, adjust=False).mean(), "vol20": df.Volume.rolling(20).mean()}


def gates(df, lessons):
    i = ind(df)
    cl, e9, e21 = float(df.Close.iloc[-1]), float(i["e9"].iloc[-1]), float(i["e21"].iloc[-1])
    adx, atr = float(i["adx"].iloc[-1]), float(i["atr"].iloc[-1])
    volx = float(df.Volume.iloc[-1] / i["vol20"].iloc[-1]) if i["vol20"].iloc[-1] else 0
    runup = float(cl / df.Close.iloc[-11] - 1) * 100 if len(df) > 11 else 0
    texts = " ".join(r["lesson"] for r in lessons)
    if adx < 20:
        v = "WAIT_SIDEWAYS"
    elif not (cl > e9 > e21):
        v = "WAIT_TREND"
    elif volx < 1.5:
        v = "WAIT_VOLUME"
    elif "run-up above 8%" in texts and runup > 8:
        v = "SKIP_PRICED_IN"
    else:
        v = "ENTER"
    return v, {"close": cl, "adx": round(adx, 1), "volx": round(volx, 2), "atr": round(atr, 2), "runup_10d": round(runup, 1),
               "one_tranche": "ADX > 25 before deploying" in texts and adx <= 25}


def equity(rows):
    return BOOK + sum(r.get("pnl_rs", 0) or 0 for r in rows if r["status"] not in ("OPEN", "PENDING"))


def settle(rows, lessons, bars, nifty):
    for r in [r for r in rows if r["status"] in ("PENDING", "OPEN")]:
        df = bars.get(r["ticker"])
        if df is None or df.empty:
            continue
        i = ind(df)
        after = df[df.index > pd.Timestamp(r["signal_date"])]
        if r["status"] == "PENDING":
            if after.empty:
                continue
            o = float(after.Open.iloc[0])
            atr0 = float(i["atr"].loc[: after.index[0]].iloc[-2])
            r.update(status="OPEN", opened=str(after.index[0].date()), entry=round(o, 2), atr0=round(atr0, 2),
                     stop=round(o - 1.5 * atr0, 2), qty=int(r["deploy_rs"] // o))
            if r["qty"] < 1:
                r.update(status="SKIPPED", note="One share costs more than the tranche.")
                continue
        walk = df[df.index >= pd.Timestamp(r["opened"])]
        entry, stop, atr0, hiwater, be = r["entry"], r["stop"], r["atr0"], r["entry"], r.get("be", False)
        exit_px = why = None
        for n, (ts, row) in enumerate(walk.iterrows()):
            lo, cl = float(row.Low), float(row.Close)
            if lo <= stop:
                exit_px, why = stop, "stop"
                break
            hiwater = max(hiwater, cl)
            if not be and cl >= entry + 1.5 * (entry - r["stop"]):
                be, stop = True, max(stop, entry)
            if be:
                stop = max(stop, max(float(i["e9"].loc[ts]), cl - float(i["atr"].loc[ts])))
            if n >= 5 and hiwater - entry < 0.5 * atr0:
                exit_px, why = cl, "sideways"
                break
        r.update(stop=round(stop, 2), be=be)
        if exit_px is None:
            last = float(walk.Close.iloc[-1])
            r.update(last_close=round(last, 2), unreal_rs=round(r["qty"] * (last - entry) - COST * entry * r["qty"], 2))
            continue
        pnl = round(r["qty"] * (exit_px - entry) - COST * entry * r["qty"], 2)
        r.update(status="WIN" if pnl > 0 else ("SIDEWAYS_EXIT" if why == "sideways" else "LOSS"), exit=round(exit_px, 2),
                 closed=str(ts.date()), pnl_rs=pnl, unreal_rs=0, note=f"Closed on {why}.")
        if pnl <= 0:
            diag, rule = [], ""
            nf = nifty[(nifty.index >= pd.Timestamp(r["opened"])) & (nifty.index <= ts)]
            nret = float(nf.Close.iloc[-1] / nf.Close.iloc[0] - 1) * 100 if len(nf) > 1 else 0
            if nret < -1:
                diag.append(f"Nifty fell {nret:.1f}% during the hold"); rule = "Lesson: index divergence — stand aside when the Nifty itself is falling."
            if r.get("runup_10d", 0) > 8:
                diag.append(f"already up {r['runup_10d']}% in the 10 days before entry"); rule = "Lesson: priced in — skip entries after a 10-day run-up above 8%."
            if why == "sideways" and r.get("adx_at_entry", 99) <= 25:
                diag.append(f"ADX was {r.get('adx_at_entry')} at entry"); rule = "Lesson: require ADX > 25 before deploying more than one tranche."
            if not rule:
                rule = "Lesson: the stop of 1.5x ATR was hit in a live trend; normal cost of the method, no rule change."
            lessons.append({"date": str(ts.date()), "ticker": r["ticker"], "exit": why, "pnl_rs": pnl,
                            "diagnosis": "; ".join(diag) or "no outside cause found", "lesson": rule})


def main():
    import yfinance as yf
    rows, lessons = jload(LED, []), jload(LES, [])
    files = sorted((ROOT / "reports").glob("*_agents.json"))
    room = json.loads(files[-1].read_text()) if files else {}
    signals = make_signals(room)
    ticks = sorted({r["ticker"] for r in rows if r["status"] in ("PENDING", "OPEN")} | {s["ticker"] for s in signals if s["eligible"] == "yes"} | {"^NSEI"})
    data = yf.download(ticks, period="1y", group_by="ticker", auto_adjust=False, threads=True, progress=False)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from paper_engine import complete
    bars = {}
    for t in ticks:
        try:
            bars[t] = complete(data[t].dropna(subset=["Close"])) if len(ticks) > 1 else complete(data.dropna(subset=["Close"]))
        except KeyError:
            pass
    settle(rows, lessons, bars, bars.get("^NSEI", pd.DataFrame()))
    open_now = [r for r in rows if r["status"] in ("PENDING", "OPEN")]
    cash = equity(rows) - sum(r.get("deploy_rs", 0) for r in open_now)
    nid = max([r["id"] for r in rows], default=0)
    for s in signals:
        df = bars.get(s["ticker"])
        if s["eligible"] != "yes" or df is None or len(df) < 60:
            s["verdict"] = s["verdict"] or ("LOW_CONVICTION" if s["eligible"] != "yes" else "NO_DATA")
            continue
        v, g = gates(df, lessons)
        s["verdict"] = v
        s["note"] = f"close {g['close']:.2f}, ADX {g['adx']}, volume {g['volx']}x, 10-day run-up {g['runup_10d']}%"
        if v != "ENTER" or any(r["ticker"] == s["ticker"] for r in open_now) or len(open_now) >= MAX_OPEN:
            continue
        all_in = s["conviction"] >= 0.90 and g["adx"] > 25 and not g["one_tranche"]
        deploy = round(cash if all_in else min(cash, equity(rows) / TRANCHES), 2)
        if deploy < g["close"]:
            s["note"] += "; no cash free for a new tranche"
            continue
        nid += 1
        rows.append({"id": nid, "ticker": s["ticker"], "strategy": "signal_desk", "conviction": s["conviction"], "status": "PENDING",
                     "signal_date": str(df.index[-1].date()), "signal_close": g["close"], "deploy_rs": deploy, "all_in": all_in,
                     "adx_at_entry": g["adx"], "runup_10d": g["runup_10d"], "entry": g["close"], "stop": round(g["close"] - 1.5 * g["atr"], 2),
                     "atr0": g["atr"], "qty": 0, "opened": "", "closed": "", "exit": "", "pnl_rs": 0, "be": False,
                     "note": ("everything available: conviction and trend both strong" if all_in else "one tranche") + "; fills at the next open"})
        cash -= deploy
        open_now.append(rows[-1])
    DATA.mkdir(parents=True, exist_ok=True)
    LED.write_text(json.dumps(rows, indent=1))
    LES.write_text(json.dumps(lessons[-40:], indent=1))
    SIG.write_text(json.dumps(signals, indent=1))
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    print(f"signal desk: {len(signals)} signals, ledger {len(rows)} {by}, equity {equity(rows):,.0f}, lessons {len(lessons)}")


if __name__ == "__main__":
    main()
