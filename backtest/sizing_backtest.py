"""Backtest of the position-sizing rule in the Caution regime.

Question: should trades taken in the Caution regime (India VIX 16-20, or Nifty
below its 200-day average) be half size (0.5% risk) or full size (1% risk)?

The live desk picks ideas with LLM analysts and news catalysts, which cannot be
replayed historically. This backtest uses a MECHANICAL PROXY for idea selection
(the package's momentum screen) so that only the sizing rule differs between
variants. It tests the sizing rule, not the quality of the live picks.

Rules simulated (from the daily report's policy summary):
  * signal at the close, entry at the next session's open
  * at most one new idea per day, max 4 open positions
  * stop and target as fixed % of entry; stop assumed first if both hit in a bar;
    gaps through a level fill at the open
  * risk per trade 1% of equity (Normal); Caution is 0.5% or 1% by variant
  * position value capped at 30% of equity, total open risk capped at 4%
  * CASH (no new entries): VIX > 20, or Nifty fell more than 2% that session
  * time stop after 40 sessions
  * breakers: 3 losses in a row -> 3 sessions without entries;
    drawdown >= 6% from the reference peak -> 5 sessions without entries,
    then the reference resets
  * optional trailing rule: stop moves to entry once the high reaches +2R
  * costs: 0.25% of traded value per round trip

Usage: python backtest/sizing_backtest.py [--years 5] [--cache DIR]
"""
from __future__ import annotations

import argparse
import math
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

UNIVERSE = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "KOTAKBANK", "SBIN", "AXISBANK",
    "BHARTIARTL", "ITC", "LT", "HINDUNILVR", "BAJFINANCE", "MARUTI", "M&M", "TITAN",
    "SUNPHARMA", "ASIANPAINT", "ULTRACEMCO", "NTPC", "POWERGRID", "TATASTEEL", "JSWSTEEL",
    "HINDALCO", "ADANIPORTS", "BEL", "ETERNAL", "HCLTECH", "WIPRO", "TECHM", "NESTLEIND",
    "BAJAJFINSV", "COALINDIA", "ONGC", "GRASIM", "DRREDDY", "CIPLA", "EICHERMOT",
    "HEROMOTOCO", "BAJAJ-AUTO", "INDUSINDBK", "APOLLOHOSP", "DIVISLAB", "BRITANNIA",
    "TATACONSUM", "ADANIENT", "HDFCLIFE", "SBILIFE", "SHRIRAMFIN", "TRENT",
]
COST_ROUND_TRIP = 0.0025
START_EQUITY = 100_000.0


def load_data(years: int, cache: Path | None):
    if cache and (cache / "bt_data.pkl").exists():
        return pickle.loads((cache / "bt_data.pkl").read_bytes())
    import yfinance as yf
    period = f"{years + 2}y"  # extra history to warm up the 200-day average
    out = {}
    for t in UNIVERSE + ["^NSEI", "^INDIAVIX"]:
        sym = t if t.startswith("^") else f"{t}.NS"
        try:
            df = yf.Ticker(sym).history(period=period, auto_adjust=False)
        except Exception:
            continue
        df = df[["Open", "High", "Low", "Close"]].dropna()
        df = df[(df > 0).all(axis=1) & (df["High"] >= df["Low"])]
        df.index = pd.to_datetime(df.index.date)
        df = df[~df.index.duplicated()]
        if len(df) > 260:
            out[t] = df
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "bt_data.pkl").write_bytes(pickle.dumps(out))
    return out


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Same screen as trading_team.indicators.screen_score, vectorised."""
    c = df["Close"]
    sma50, sma200 = c.rolling(50).mean(), c.rolling(200).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    ret1m, ret3m = c / c.shift(21) - 1, c / c.shift(63) - 1
    trend = np.where((c > sma50) & (sma50 > sma200), 2.0,
                     np.where((c < sma50) & (sma50 < sma200), -2.0, 0.0))
    score = (trend + ((rsi >= 45) & (rsi <= 70)) * 1.0 + (hist > 0) * 1.0
             + (ret1m > 0) * 1.0)
    df = df.copy()
    df["score"] = np.where(sma200.notna(), score, np.nan)
    df["ret3m"] = ret3m
    return df


@dataclass
class Pos:
    ticker: str
    qty: int
    entry: float
    stop: float
    target: float
    risk_rupees: float
    regime: str
    age: int = 0
    armed: bool = False  # breakeven stop becomes active the session after +2R


def run(data, start, *, caution_risk, trail, stop_pct=0.04, target_pct=0.20,
        min_score=5.0):
    nifty, vix = data["^NSEI"], data["^INDIAVIX"]
    stocks = {t: add_signals(df) for t, df in data.items() if not t.startswith("^")}
    n200 = nifty["Close"].rolling(200).mean()
    nret = nifty["Close"].pct_change()
    days = [d for d in nifty.index if d >= start]

    cash, positions, trades, curve = START_EQUITY, [], [], []
    peak, pause, loss_streak, pending = START_EQUITY, 0, 0, None
    ref_peak, breaker_hits = START_EQUITY, 0
    regime_days = {"NORMAL": 0, "CAUTION": 0, "CASH": 0}
    max_dd = 0.0

    def close_px(t, d):
        df = stocks[t]
        return df["Close"].asof(d)

    for d in days:
        # 1. execute yesterday's signal at today's open
        if pending and pending["ticker"] in stocks and d in stocks[pending["ticker"]].index:
            t, regime = pending["ticker"], pending["regime"]
            o = float(stocks[t].at[d, "Open"])
            equity = cash + sum(p.qty * close_px(p.ticker, d - pd.Timedelta(days=1))
                                for p in positions)
            risk_frac = 0.01 if regime == "NORMAL" else caution_risk
            open_risk = sum(p.risk_rupees for p in positions)
            budget = min(risk_frac * equity, 0.04 * equity - open_risk)
            qty = math.floor(budget / (o * stop_pct)) if budget > 0 else 0
            qty = min(qty, math.floor(0.30 * equity / o), math.floor(cash / o))
            if qty > 0 and len(positions) < 4:
                cash -= qty * o
                positions.append(Pos(t, qty, o, o * (1 - stop_pct), o * (1 + target_pct),
                                     qty * o * stop_pct, regime))
        pending = None

        # 2. manage open positions on today's bar
        for p in positions[:]:
            df = stocks[p.ticker]
            if d not in df.index:
                continue
            o, h, l, c = (float(df.at[d, k]) for k in ("Open", "High", "Low", "Close"))
            p.age += 1
            stop = p.entry if (trail and p.armed) else p.stop
            exit_px = None
            if o <= stop:
                exit_px = o
            elif l <= stop:
                exit_px = stop
            elif o >= p.target:
                exit_px = o
            elif h >= p.target:
                exit_px = p.target
            elif p.age >= 40:
                exit_px = c
            if exit_px is None:
                if h >= p.entry + 2 * (p.entry - p.stop):
                    p.armed = True
                continue
            cost = COST_ROUND_TRIP * p.qty * p.entry
            pnl = p.qty * (exit_px - p.entry) - cost
            cash += p.qty * exit_px - cost
            positions.remove(p)
            trades.append({"exit": d, "ticker": p.ticker, "regime": p.regime, "pnl": pnl,
                           "R": pnl / p.risk_rupees, "ret": exit_px / p.entry - 1})
            if pnl < 0:
                loss_streak += 1
                if loss_streak >= 3:
                    pause, loss_streak = max(pause, 3), 0
            else:
                loss_streak = 0

        # 3. mark to market, breakers
        equity = cash + sum(p.qty * close_px(p.ticker, d) for p in positions)
        peak = max(peak, equity)
        max_dd = max(max_dd, 1 - equity / peak)
        # The 6% breaker is measured from a reference peak that resets when the
        # breaker fires, so trading resumes after the 5-session pause.
        ref_peak = max(ref_peak, equity)
        if 1 - equity / ref_peak >= 0.06:
            pause, ref_peak = max(pause, 5), equity
            breaker_hits += 1
        curve.append((d, equity))

        # 4. regime at the close, and tomorrow's signal
        v = vix["Close"].asof(d)
        if np.isnan(v) or v > 20 or nret.get(d, 0) < -0.02:
            regime = "CASH"
        elif v >= 16 or nifty.at[d, "Close"] < n200.get(d, np.nan):
            regime = "CAUTION"
        else:
            regime = "NORMAL"
        regime_days[regime] += 1
        if pause > 0:
            pause -= 1
            continue
        if regime == "CASH" or len(positions) >= 4:
            continue
        held = {p.ticker for p in positions}
        best = None
        for t, df in stocks.items():
            if t in held or d not in df.index:
                continue
            s = df.at[d, "score"]
            if np.isnan(s) or s < min_score:
                continue
            key = (s, df.at[d, "ret3m"])
            if best is None or key > best[0]:
                best = (key, t)
        if best:
            pending = {"ticker": best[1], "regime": regime}

    eq = pd.Series(dict(curve))
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    tr = pd.DataFrame(trades)
    return {"equity": eq, "trades": tr, "cagr": (eq.iloc[-1] / START_EQUITY) ** (1 / yrs) - 1,
            "max_dd": max_dd, "final": eq.iloc[-1], "breaker_hits": breaker_hits, "regime_days": regime_days, "years": yrs}


def summarise(name, r):
    tr = r["trades"]
    line = (f"{name:<34} final Rs{r['final']:>9,.0f}  CAGR {r['cagr']*100:>5.1f}%  "
            f"maxDD {r['max_dd']*100:>4.1f}%  trades {len(tr):>3}")
    if len(tr):
        line += f"  win {100*(tr.pnl>0).mean():>4.1f}%  avgR {tr.R.mean():>+5.2f}"
    line += f"  6%-breaker hits {r['breaker_hits']}"
    return line


def by_regime(tr):
    rows = []
    for reg, g in tr.groupby("regime"):
        se = g.R.std(ddof=1) / math.sqrt(len(g)) if len(g) > 1 else float("nan")
        rows.append(f"  {reg:<8} n={len(g):>3}  win {100*(g.pnl>0).mean():>4.1f}%  "
                    f"avgR {g.R.mean():>+5.2f} (std err {se:.2f})  "
                    f"avg return {100*g.ret.mean():>+5.2f}%")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--cache", type=Path, default=None)
    args = ap.parse_args()
    data = load_data(args.years, args.cache)
    nifty = data["^NSEI"]
    start = nifty.index[-1] - pd.DateOffset(years=args.years)
    n = nifty[nifty.index >= start]["Close"]
    yrs = (n.index[-1] - n.index[0]).days / 365.25
    print(f"Period {n.index[0].date()} to {n.index[-1].date()}  "
          f"universe {len(data) - 2} stocks")
    print(f"Nifty 50 buy-and-hold (price only): CAGR "
          f"{((n.iloc[-1] / n.iloc[0]) ** (1 / yrs) - 1) * 100:.1f}%  "
          f"maxDD {(1 - n / n.cummax()).max() * 100:.1f}%\n")

    results = {}
    for trail in (False, True):
        for cr, label in ((0.005, "half size in Caution"), (0.01, "FULL size in Caution")):
            name = f"{label}{' + breakeven trail' if trail else ''}"
            results[name] = run(data, start, caution_risk=cr, trail=trail)
            print(summarise(name, results[name]))
    base = results["half size in Caution"]
    print("\nRegime days:", base["regime_days"])
    print("Trade quality by regime at entry (base variant, per-trade R is size-independent):")
    print(by_regime(base["trades"]))

    print("\nBy calendar year, equity change % (half vs full, no trail):")
    full = results["FULL size in Caution"]
    for y in sorted(set(base["equity"].index.year)):
        def chg(r):
            e = r["equity"][r["equity"].index.year == y]
            prev = r["equity"][r["equity"].index.year < y]
            b = prev.iloc[-1] if len(prev) else START_EQUITY
            return (e.iloc[-1] / b - 1) * 100
        print(f"  {y}: half {chg(base):>+6.1f}%   full {chg(full):>+6.1f}%")

    print("\nRobustness: CAGR / maxDD, half vs full (no trail)")
    for sp, tp, ms in ((0.03, 0.15, 5), (0.04, 0.20, 4), (0.05, 0.30, 5), (0.05, 0.15, 5),
                       (0.03, 0.30, 5)):
        a = run(data, start, caution_risk=0.005, trail=False, stop_pct=sp, target_pct=tp,
                min_score=ms)
        b = run(data, start, caution_risk=0.01, trail=False, stop_pct=sp, target_pct=tp,
                min_score=ms)
        print(f"  stop {sp*100:.0f}% target {tp*100:.0f}% min score {ms}: "
              f"half {a['cagr']*100:>+5.1f}% / {a['max_dd']*100:>4.1f}%   "
              f"full {b['cagr']*100:>+5.1f}% / {b['max_dd']*100:>4.1f}%   "
              f"trades {len(a['trades'])}/{len(b['trades'])}")


if __name__ == "__main__":
    main()
