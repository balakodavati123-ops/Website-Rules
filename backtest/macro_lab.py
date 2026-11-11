"""Crypto and commodities: do three classic, published trend strategies have an edge?

Strategies (fixed rules, no tuning, long-only):
  donchian_20_10  Turtle System 1: buy a close above the prior 20-day high, exit on a
                  close below the prior 10-day low.
  golden_cross    Buy when the 50-day average crosses above the 200-day, exit when it
                  crosses back below.
  momentum_12_1   Buy when the 12-month return (skipping the last month) is positive and
                  price is above its 100-day average, exit when either turns false.
Every trade: signal at the close, entry at the next open, initial stop 2 x ATR(20) below
entry (gap through the stop fills at the open), exit signal also fills at the next open.
R = profit / initial risk. Costs: 0.4% round trip for crypto, 0.15% for commodities.

Data is Yahoo Finance daily bars: spot-like crypto pairs and COMEX/NYMEX futures. These are
proxies for what trades on Gemini and MCX, not the same contracts.

Usage: python backtest/macro_lab.py [--cache DIR]
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

INSTRUMENTS = {
    "BTC-USD": ("Bitcoin", "crypto"), "ETH-USD": ("Ethereum", "crypto"),
    "SOL-USD": ("Solana", "crypto"), "GC=F": ("Gold", "commodity"),
    "SI=F": ("Silver", "commodity"), "CL=F": ("Crude oil", "commodity"),
    "NG=F": ("Natural gas", "commodity"), "HG=F": ("Copper", "commodity"),
}
COST = {"crypto": 0.004, "commodity": 0.0015}
CRITERIA = {"min_trades": 60, "t_stat": 2.0}


def load(cache: Path | None) -> dict[str, pd.DataFrame]:
    f = cache / "macro.pkl" if cache else None
    if f and f.exists():
        return pickle.loads(f.read_bytes())
    import yfinance as yf
    out = {}
    for sym in INSTRUMENTS:
        df = yf.Ticker(sym).history(period="6y", auto_adjust=False)[["Open", "High", "Low", "Close"]].dropna()
        df = df[(df > 0).all(axis=1)]
        df.index = pd.to_datetime(df.index.date)
        out[sym] = df[~df.index.duplicated()]
    if f:
        cache.mkdir(parents=True, exist_ok=True)
        f.write_bytes(pickle.dumps(out))
    return out


def atr(df, n=20):
    pc = df.Close.shift(1)
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def signals(df, name):
    """(enter, exit) boolean Series evaluated at each close."""
    c = df.Close
    if name == "donchian_20_10":
        return c > c.shift(1).rolling(20).max(), c < c.shift(1).rolling(10).min()
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    if name == "golden_cross":
        return (s50 > s200) & (s50.shift(1) <= s200.shift(1)), s50 < s200
    mom = c.shift(21) / c.shift(252) - 1
    on = (mom > 0) & (c > c.rolling(100).mean())
    return on & ~on.shift(1, fill_value=False), ~on


def run(df, name, cost):
    enter, leave = signals(df, name)
    a = atr(df)
    o, h, l, c = (df[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    e, x, av = enter.to_numpy(), leave.to_numpy(), a.to_numpy()
    trades, pos = [], None
    for i in range(1, len(df)):
        if pos:
            px = None
            if o[i] <= pos["stop"]:
                px = o[i]
            elif l[i] <= pos["stop"]:
                px = pos["stop"]
            elif x[i - 1]:
                px = o[i]
            if px is not None:
                risk = pos["entry"] - pos["stop"]
                pnl = px - pos["entry"] - cost * pos["entry"]
                trades.append({"entry": df.index[pos["i"]], "exit": df.index[i],
                               "R": pnl / risk, "ret": px / pos["entry"] - 1})
                pos = None
        if pos is None and e[i - 1] and not np.isnan(av[i - 1]):
            stop = o[i] - 2 * av[i - 1]
            if stop > 0 and o[i] > stop:
                pos = {"i": i, "entry": o[i], "stop": stop}
    return pd.DataFrame(trades), enter, leave


def stats(tr: pd.DataFrame, seed=5) -> dict:
    if len(tr) < 5:
        return {"trades": len(tr)}
    R = tr.R.to_numpy()
    n, mean, sd = len(R), R.mean(), R.std(ddof=1)
    t = mean / (sd / math.sqrt(n))
    month = tr.entry.dt.to_period("M").astype(str).to_numpy()
    groups = [R[month == m] for m in np.unique(month)]
    rng = np.random.default_rng(seed)
    means = [np.concatenate([groups[j] for j in rng.choice(len(groups), len(groups))]).mean()
             for _ in range(5000)]
    half = tr.entry.sort_values().iloc[n // 2]
    return {"trades": n, "win_rate": float((R > 0).mean()), "avg_R": float(mean), "t_stat": float(t),
            "conf_naive": float(0.5 * (1 + math.erf(t / math.sqrt(2)))),
            "conf_cluster": float(1 - (np.array(means) <= 0).mean()),
            "avg_R_first_half": float(tr[tr.entry < half].R.mean()),
            "avg_R_second_half": float(tr[tr.entry >= half].R.mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=None)
    args = ap.parse_args()
    data = load(args.cache)
    out = {"criteria": CRITERIA, "buy_and_hold": {}, "strategies": {}, "instruments": {}, "signals": []}
    for sym, df in data.items():
        yrs = (df.index[-1] - df.index[0]).days / 365.25
        out["buy_and_hold"][sym] = round(((df.Close.iloc[-1] / df.Close.iloc[0]) ** (1 / yrs) - 1) * 100, 1)
    print("Buy-and-hold per year %:", out["buy_and_hold"], "\n")
    for strat in ("donchian_20_10", "golden_cross", "momentum_12_1"):
        pooled = {"crypto": [], "commodity": []}
        for sym, df in data.items():
            kind = INSTRUMENTS[sym][1]
            tr, enter, leave = run(df, strat, COST[kind])
            tr["sym"] = sym
            pooled[kind].append(tr)
            out["instruments"].setdefault(sym, {})[strat] = stats(tr)
            in_trend = bool(enter.iloc[-1])
            out["signals"].append({"symbol": sym, "name": INSTRUMENTS[sym][0], "kind": kind,
                                   "strategy": strat, "entry_signal_today": in_trend,
                                   "last_close": round(float(df.Close.iloc[-1]), 2),
                                   "atr20": round(float(atr(df).iloc[-1]), 2),
                                   "last_date": str(df.index[-1].date())})
        for kind, frames in pooled.items():
            tr = pd.concat(frames, ignore_index=True)
            st = stats(tr)
            ok = (st["trades"] >= CRITERIA["min_trades"] and st.get("t_stat", 0) >= CRITERIA["t_stat"]
                  and st.get("avg_R_first_half", -1) > 0 and st.get("avg_R_second_half", -1) > 0)
            st["status"] = "APPROVED" if ok else ("PROBATION" if st.get("avg_R", -1) > 0 else "REJECTED")
            # Six strategy-and-asset-class combinations were tried: the best of six looks better
            # than it is, so the number that matters for the 98% gate is corrected for that.
            st["conf_adjusted"] = float(st.get("conf_cluster", 0) ** 6)   # chance it is real after 6 tries
            out["strategies"][f"{strat}:{kind}"] = st
            print(f"{strat:<16}{kind:<10} trades {st['trades']:>4}  win {st.get('win_rate', 0)*100:>4.0f}%  "
                  f"avgR {st.get('avg_R', float('nan')):>+5.2f}  t {st.get('t_stat', float('nan')):>5.2f}  "
                  f"conf {st.get('conf_cluster', 0)*100:>4.0f}%  adj {st['conf_adjusted']*100:>4.0f}%  halves "
                  f"{st.get('avg_R_first_half', float('nan')):>+5.2f}/{st.get('avg_R_second_half', float('nan')):>+5.2f}"
                  f"  {st['status']}")
    (Path(__file__).resolve().parent / "macro_lab_results.json").write_text(json.dumps(out, indent=2))
    print("\nwrote backtest/macro_lab_results.json")


if __name__ == "__main__":
    main()
