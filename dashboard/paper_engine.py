"""Paper-trading engine for the CEO Trading Desk.

It keeps the paper ledger honest and deterministic. Each run it:
  1. fills PENDING orders at the next session's open (skipped if the gap is over 3%, the book
     is full, or the size is below one share);
  2. replays every OPEN trade bar by bar and closes it on the first stop, target, exit signal
     or time stop;
  3. adds new PENDING orders for fresh signals;
  4. writes one equity point (start + realised + unrealised profit).

Rules match the backtests: signal at the close, fill at the next open, stop assumed first when a
bar touches both, a gap through a level fills at the open, 0.25% round-trip cost on stocks and
0.4% on crypto. Each stock strategy keeps its own exits (PLAN below): a fixed target, a trailing
stop 3 ATR under the highest close, a close under the 50-day average, or a bounce over the 5-day
average, each with its own time stop. Crypto: stop 2 x ATR(20), exit on a close below the prior
10-day low (Donchian 20/10).
Size: risk 1% of equity (0.5% when India VIX is 16 or higher), position capped at 30% of
equity. Every strategy runs its own test book: at most 4 open positions and 4% open risk each,
so one strategy cannot crowd out another and each can be judged on its own trades.
"""
from __future__ import annotations

import math
from datetime import date, datetime

CLOSED = ("WIN", "LOSS", "TIME STOP")
COST = {"NSE": 0.0025, "CRYPTO": 0.004}
GAP_MAX = 0.03
STOCK_STOP, STOCK_TARGET, STOCK_HOLD = 0.05, 0.20, 40
# strategy -> (stop, fixed target or None, time stop in sessions, trailing ATR multiple or None, exit rule)
PLAN = {
    "momentum_screen": (0.04, 0.20, 40, None, None),
    "pullback_in_uptrend": (0.04, 0.20, 40, None, None),
    "breakout_52w": (STOCK_STOP, STOCK_TARGET, STOCK_HOLD, None, None),
    "breakout_52w_trail": (0.05, None, 120, 3.0, None),
    "trend_ride": (0.05, None, 120, None, "sma50"),
    "rsi2_dip": (0.05, None, 10, None, "bounce"),
}


def plan(strategy):
    return PLAN.get(strategy, PLAN["breakout_52w"])


def d(x) -> date:
    return x.date() if isinstance(x, datetime) else date.fromisoformat(str(x)[:10]) if isinstance(x, str) else x


def rule(rules, key):
    return next(r["value"] for r in rules if r["key"] == key)


def realised(ledger) -> float:
    return sum(r.get("pnl_rs") or 0 for r in ledger if r["status"] in CLOSED)


def equity_now(ledger, rules) -> float:
    unreal = sum(r.get("unrealized_rs") or 0 for r in ledger if r["status"] == "OPEN")
    return rule(rules, "paper_start") + realised(ledger) + unreal


def _yf(row) -> str:
    return f"{row['symbol']}.NS" if row["market"] == "NSE" else row["symbol"]


def _sized(row, entry, stop, equity, risk_frac, fx):
    """(qty, risk_rs) or None. Stocks trade whole shares; crypto trades fractions."""
    risk_budget = risk_frac * equity
    per_unit = (entry - stop) * (fx if row["market"] == "CRYPTO" else 1)
    if per_unit <= 0:
        return None
    qty = risk_budget / per_unit
    cap = 0.30 * equity / (entry * (fx if row["market"] == "CRYPTO" else 1))
    qty = min(qty, cap)
    if row["market"] == "NSE":
        qty = math.floor(qty)
        if qty < 1:
            return None
    else:
        qty = math.floor(qty * 1e6) / 1e6
        if qty <= 0:
            return None
    return qty, round(qty * per_unit, 2)


def try_fill(row, ledger, rules, provider):
    bars = provider.daily(_yf(row))
    after = bars[bars.index.date > d(row["signal_date"])]
    if after.empty:
        return
    day = after.index[0]
    o = float(after.iloc[0].Open)
    ref = float(row["signal_close"])
    gap = o / ref - 1
    row["opened"] = str(day.date())
    if abs(gap) > GAP_MAX:
        row.update(status="SKIPPED", note=f"Opened {gap * 100:+.1f}% from the signal close: the reason for the trade changed.")
        return
    equity = rule(rules, "paper_start") + realised(ledger)
    vix = provider.vix(d(day))
    frac = (rule(rules, "risk_caution") if vix is not None and vix >= 16 else rule(rules, "risk_normal")) / 100
    open_rows = [r for r in ledger if r["status"] == "OPEN" and r["strategy"] == row["strategy"]]
    if len(open_rows) >= 4:
        row.update(status="SKIPPED", note="Four positions already open in this strategy.")
        return
    if row["market"] == "NSE":
        p = plan(row["strategy"])
        stop, target = o * (1 - p[0]), (o * (1 + p[1]) if p[1] else "")
    else:
        stop, target = o - 2 * float(row["atr"]), ""
    fx = provider.fx() if row["market"] == "CRYPTO" else 1.0
    sized = _sized(row, o, stop, equity, frac, fx)
    if sized is None:
        row.update(status="SKIPPED", note="Position size rounds to nothing at this risk.")
        return
    qty, risk = sized
    if sum(r["risk_rs"] for r in open_rows) + risk > 0.04 * equity + 1e-9:
        row.update(status="SKIPPED", note="This strategy's open risk would pass 4% of equity.")
        return
    row.update(status="OPEN", entry=round(o, 4 if o < 1000 else 2), stop=round(stop, 4 if stop < 1000 else 2), stop0=round(stop, 4),
               target=round(target, 2) if target != "" else "", qty=qty, risk_rs=risk, fx=fx,
               note=f"Filled at the open of {day.date()}.")


def replay(row, provider):
    """Walk the bars from the fill day; close the trade on the first exit."""
    import pandas as pd
    bars = provider.daily(_yf(row))
    entry, stop = float(row["entry"]), float(row["stop"])
    stop0 = float(row.get("stop0") or row["stop"])          # R is measured from the first stop
    target = float(row["target"]) if row["target"] != "" else None
    cost = COST[row["market"]]
    crypto = row["market"] == "CRYPTO"
    c = bars.Close
    leave = (c < c.shift(1).rolling(10).min()).to_numpy() if crypto else None
    _, _, hold, trail, rule = (None, None, None, None, None) if crypto else plan(row["strategy"])
    sma50, sma5 = c.rolling(50).mean().to_numpy(), c.rolling(5).mean().to_numpy()
    atr = None
    if trail and "High" in bars:
        tr = pd.concat([bars.High - bars.Low, (bars.High - c.shift(1)).abs(), (bars.Low - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().to_numpy()
    start = bars.index.searchsorted(pd.Timestamp(d(row["opened"])))
    age, high = 0, entry
    for i in range(start, len(bars)):
        o, h, l, cl = (float(bars.iloc[i][k]) for k in ("Open", "High", "Low", "Close"))
        age += 1
        px = why = None
        if crypto and age > 1 and leave[i - 1]:
            px, why = o, "exit signal"
        elif o <= stop:
            px, why = o, "stop"
        elif l <= stop:
            px, why = stop, "stop"
        elif target and o >= target:
            px, why = o, "target"
        elif target and h >= target:
            px, why = target, "target"
        elif rule == "sma50" and age > 1 and cl < sma50[i]:
            px, why = cl, "a close under the 50-day average"
        elif rule == "bounce" and age > 1 and cl > sma5[i]:
            px, why = cl, "the bounce over the 5-day average"
        elif not crypto and age >= hold:
            px, why = cl, "time stop"
        if px is not None:
            r = (px - entry - cost * entry) / (entry - stop0)
            row.update(status="TIME STOP" if why == "time stop" else ("WIN" if r > 0 else "LOSS"), closed=str(bars.index[i].date()),
                       exit=round(px, 4 if px < 1000 else 2), r_mult=round(r, 3), pnl_rs=round(r * row["risk_rs"], 2),
                       unrealized_rs=0, note=f"Closed on {why}.")
            return
        if atr is not None and atr[i] == atr[i]:             # trail the stop under the highest close
            high = max(high, cl)
            stop = max(stop, high - trail * atr[i])
    last = float(bars.iloc[-1].Close)
    r = (last - entry - cost * entry) / (entry - stop0)
    row.update(unrealized_rs=round(r * row["risk_rs"], 2), r_mult=round(r, 3), last_close=round(last, 4 if last < 1000 else 2),
               stop=round(stop, 4 if stop < 1000 else 2))


def add_signals(ledger, signals, rules):
    """signals: [{market, symbol, strategy, signal_date, signal_close, atr?}]"""
    live = {(r["market"], r["symbol"], r["strategy"]) for r in ledger if r["status"] in ("PENDING", "OPEN")}
    seen_today = {(r["market"], r["symbol"], r["strategy"], r.get("signal_date")) for r in ledger}
    nid = max([r["id"] for r in ledger], default=0)
    for s in signals:
        key = (s["market"], s["symbol"], s["strategy"])
        if key in live or key + (s["signal_date"],) in seen_today:
            continue
        nid += 1
        ref = float(s["signal_close"])
        p = plan(s["strategy"])
        stop = ref * (1 - p[0]) if s["market"] == "NSE" else ref - 2 * float(s["atr"])
        ledger.append({"id": nid, "market": s["market"], "symbol": s["symbol"], "strategy": s["strategy"], "status": "PENDING",
                       "signal_date": str(s["signal_date"]), "signal_close": ref, "atr": s.get("atr", ""), "opened": "", "closed": "",
                       "entry": ref, "stop": round(stop, 4 if stop < 1000 else 2),
                       "target": round(ref * (1 + p[1]), 2) if s["market"] == "NSE" and p[1] else "", "qty": "", "risk_rs": "",
                       "exit": "", "pnl_rs": 0, "r_mult": 0, "note": "Signal at the close. Fills at the next open if the gap is within 3%."})
        live.add(key)
    return ledger


def step(ledger, equity, rules, signals, provider, today):
    """One engine run. Returns (ledger, equity) as new lists."""
    ledger = [dict(r) for r in ledger]
    for row in sorted(ledger, key=lambda r: r["id"]):
        if row["status"] == "PENDING":
            try_fill(row, ledger, rules, provider)
        if row["status"] == "OPEN":
            replay(row, provider)
    add_signals(ledger, signals, rules)
    eq = [dict(e) for e in equity if e["date"] != str(today)]
    eq.append({"date": str(today), "equity": round(equity_now(ledger, rules), 2)})
    return ledger, sorted(eq, key=lambda e: e["date"])


class YahooProvider:
    """Daily bars from Yahoo Finance, cached per run."""

    def __init__(self):
        import yfinance as yf
        self._yf, self._cache, self._pre = yf, {}, {}

    def daily(self, sym):
        if sym not in self._cache:
            df = self._pre.get(sym)
            if df is None:
                df = self._yf.Ticker(sym).history(period="2y", auto_adjust=False)
            df = df[["Open", "High", "Low", "Close"]].dropna()
            df.index = __import__("pandas").to_datetime(df.index.date)
            self._cache[sym] = df
        return self._cache[sym]

    def vix(self, day):
        try:
            v = self.daily("^INDIAVIX")
            v = v[v.index.date <= day]
            return float(v.Close.iloc[-1]) if len(v) else None
        except Exception:
            return None

    def fx(self):
        return float(self.daily("INR=X").Close.iloc[-1])
