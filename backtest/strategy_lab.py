"""Strategy lab: decides which entry strategies the live desk may use.

Every strategy in trading_team/strategies.py is replayed over 5 years on the
wide universe under the desk's portfolio rules, after costs. A strategy is
APPROVED only if it meets every criterion in CRITERIA, which were fixed before
looking at results. The verdicts are written to approved_strategies.json and
read by the live screen.

Portfolio rules simulated: signal at the close, entry at the next open; one new
idea per day; max 4 positions; risk 1% of equity per trade (0.5% in Caution);
30% position cap; 4% total open risk cap; no entries when VIX > 20 or Nifty fell
more than 2%; pause after 3 straight losses (3 sessions) or a 6% drawdown
(5 sessions); stop assumed first when stop and target fall in one bar; gaps fill
at the open; 0.25% round-trip cost.

Known limits: the universe is today's index members (survivorship bias, which
flatters every strategy, trend strategies most); prices are daily bars from
Yahoo Finance; dividends are ignored.

Usage: python backtest/strategy_lab.py [--years 5] [--cache DIR]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from trading_team.strategies import STRATEGIES, Strategy  # noqa: E402
from universe import add_earnings, fetch_universe  # noqa: E402

COST = 0.0025
START_EQUITY = 100_000.0
CRITERIA = {
    "min_trades": 100,
    "min_avg_R": 0.0,          # strictly above
    "min_t_stat": 2.0,         # avg R / standard error
    "both_halves_positive": True,   # avg R > 0 in first 60% and last 40% of the period
    "max_drawdown": 0.20,
    "min_cagr": 0.0,           # strictly above
}


def build(data: dict[str, pd.DataFrame], strat: Strategy):
    cal = data["^NSEI"].index
    names = [t for t in data if not t.startswith("^")]
    shape = (len(cal), len(names))
    O, H, L, C = (np.full(shape, np.nan) for _ in range(4))
    S = np.full(shape, np.nan)
    X = np.zeros(shape, dtype=bool)
    A = np.full(shape, np.nan)  # ATR(14), for trailing exits
    for j, t in enumerate(names):
        df = data[t]
        score, exit_ = strat.fn(df)
        # require a valid 200-day average so every strategy starts on equal footing
        score = score.where(df["Close"].rolling(200).mean().notna())
        pc = df["Close"].shift(1)
        tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(),
                        (df["Low"] - pc).abs()], axis=1).max(axis=1)
        A[:, j] = tr.ewm(alpha=1 / 14, adjust=False).mean().reindex(cal).to_numpy()
        r = df.reindex(cal)
        O[:, j], H[:, j], L[:, j], C[:, j] = r.Open, r.High, r.Low, r.Close
        S[:, j] = score.reindex(cal).to_numpy(dtype=float)
        if exit_ is not None:
            X[:, j] = exit_.reindex(cal).fillna(False).to_numpy(dtype=bool)
    Cff = pd.DataFrame(C).ffill().to_numpy()
    nifty = data["^NSEI"]["Close"]
    vix = data["^INDIAVIX"]["Close"].reindex(cal).ffill().to_numpy()
    n200 = nifty.rolling(200).mean().to_numpy()
    nret = nifty.pct_change().to_numpy()
    nc = nifty.to_numpy()
    regime = np.where(np.isnan(vix) | (vix > 20) | (nret < -0.02), 2,
                      np.where((vix >= 16) | (nc < n200), 1, 0))  # 0 normal 1 caution 2 cash
    return cal, names, O, H, L, C, Cff, S, X, A, regime


def simulate(data, strat: Strategy, start):
    cal, names, O, H, L, C, Cff, S, X, A, regime = build(data, strat)
    i0 = int(np.searchsorted(cal, start))
    cash, pos, trades, curve = START_EQUITY, [], [], []
    peak = ref_peak = START_EQUITY
    pause = streak = 0
    pending = None
    max_dd = 0.0
    for i in range(i0, len(cal)):
        if pending is not None:
            j, reg = pending
            o = O[i, j]
            if not np.isnan(o) and len(pos) < 4:
                equity = cash + sum(p["q"] * Cff[i - 1, p["j"]] for p in pos)
                frac = 0.01 if reg == 0 else 0.005
                budget = min(frac * equity, 0.04 * equity - sum(p["risk"] for p in pos))
                q = math.floor(budget / (o * strat.stop_pct)) if budget > 0 else 0
                q = min(q, math.floor(0.30 * equity / o), math.floor(cash / o))
                if q > 0:
                    cash -= q * o
                    pos.append({"j": j, "q": q, "e": o, "stop": o * (1 - strat.stop_pct),
                                "tgt": o * (1 + strat.target_pct) if strat.target_pct else None,
                                "risk": q * o * strat.stop_pct, "age": 0, "i": i,
                                "hi": o, "leave": False})
            pending = None

        for p in pos[:]:
            j = p["j"]
            o, h, l, c = O[i, j], H[i, j], L[i, j], C[i, j]
            if np.isnan(o):
                continue
            p["age"] += 1
            px = None
            if p["leave"] or (p["age"] > 1 and X[i - 1, j]):
                px = o
            elif o <= p["stop"]:
                px = o
            elif l <= p["stop"]:
                px = p["stop"]
            elif p["tgt"] and o >= p["tgt"]:
                px = o
            elif p["tgt"] and h >= p["tgt"]:
                px = p["tgt"]
            elif p["age"] >= strat.max_hold:
                px = c
            if px is None:
                p["hi"] = max(p["hi"], c)
                if strat.trail_atr and not np.isnan(A[i, j]) \
                        and c < p["hi"] - strat.trail_atr * A[i, j]:
                    p["leave"] = True  # exit at the next open
                continue
            cost = COST * p["q"] * p["e"]
            pnl = p["q"] * (px - p["e"]) - cost
            cash += p["q"] * px - cost
            pos.remove(p)
            trades.append({"entry_i": p["i"], "R": pnl / p["risk"], "pnl": pnl,
                           "ret": px / p["e"] - 1, "hold": p["age"]})
            streak = streak + 1 if pnl < 0 else 0
            if streak >= 3:
                pause, streak = max(pause, 3), 0

        equity = cash + sum(p["q"] * Cff[i, p["j"]] for p in pos)
        peak = max(peak, equity)
        max_dd = max(max_dd, 1 - equity / peak)
        ref_peak = max(ref_peak, equity)
        if 1 - equity / ref_peak >= 0.06:
            pause, ref_peak = max(pause, 5), equity
        curve.append(equity)

        if pause > 0:
            pause -= 1
            continue
        if regime[i] == 2 or len(pos) >= 4:
            continue
        row = S[i].copy()
        for p in pos:
            row[p["j"]] = np.nan
        if not np.all(np.isnan(row)):
            pending = (int(np.nanargmax(row)), int(regime[i]))

    tr = pd.DataFrame(trades)
    years = (cal[-1] - cal[i0]).days / 365.25
    split_i = i0 + int(0.6 * (len(cal) - i0))
    out = {"trades": len(tr), "final_equity": round(curve[-1]),
           "cagr": (curve[-1] / START_EQUITY) ** (1 / years) - 1, "max_dd": max_dd}
    if len(tr):
        se = tr.R.std(ddof=1) / math.sqrt(len(tr)) if len(tr) > 1 else float("nan")
        first, second = tr[tr.entry_i < split_i], tr[tr.entry_i >= split_i]
        out.update({
            "win_rate": float((tr.pnl > 0).mean()), "avg_R": float(tr.R.mean()),
            "t_stat": float(tr.R.mean() / se) if se and se > 0 else float("nan"),
            "avg_hold": float(tr.hold.mean()),
            "avg_R_first_60pct": float(first.R.mean()) if len(first) else float("nan"),
            "avg_R_last_40pct": float(second.R.mean()) if len(second) else float("nan"),
            "trades_first": len(first), "trades_last": len(second)})
    return out


def verdict(r: dict) -> tuple[bool, list[str]]:
    fails = []
    if r["trades"] < CRITERIA["min_trades"]:
        fails.append(f"only {r['trades']} trades (need {CRITERIA['min_trades']})")
    if not r.get("avg_R", -1) > CRITERIA["min_avg_R"]:
        fails.append(f"average R {r.get('avg_R', float('nan')):+.2f} is not positive")
    if not r.get("t_stat", -1) >= CRITERIA["min_t_stat"]:
        fails.append(f"t-stat {r.get('t_stat', float('nan')):.2f} below {CRITERIA['min_t_stat']}")
    if not (r.get("avg_R_first_60pct", -1) > 0 and r.get("avg_R_last_40pct", -1) > 0):
        fails.append("not positive in both parts of the period")
    if r["max_dd"] > CRITERIA["max_drawdown"]:
        fails.append(f"drawdown {r['max_dd']*100:.0f}% above {CRITERIA['max_drawdown']*100:.0f}%")
    if not r["cagr"] > CRITERIA["min_cagr"]:
        fails.append(f"return {r['cagr']*100:+.1f}% a year is not positive")
    return (not fails), fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--cache", type=Path, default=None)
    args = ap.parse_args()
    data = fetch_universe(args.years, args.cache)
    n_earn = add_earnings(data, args.cache)
    print(f"earnings history for {n_earn} tickers")
    nifty = data["^NSEI"]["Close"]
    start = nifty.index[-1] - pd.DateOffset(years=args.years)
    n = nifty[nifty.index >= start]
    years = (n.index[-1] - n.index[0]).days / 365.25
    bench = {"cagr": float((n.iloc[-1] / n.iloc[0]) ** (1 / years) - 1),
             "max_dd": float((1 - n / n.cummax()).max())}
    tradable = len(data) - 2
    print(f"Period {n.index[0].date()} to {n.index[-1].date()}, {tradable} tickers")
    print(f"Nifty 50 buy-and-hold (price only): {bench['cagr']*100:+.1f}% a year, "
          f"max drawdown {bench['max_dd']*100:.1f}%\n")

    report = {"generated": date.today().isoformat(),
              "period": [str(n.index[0].date()), str(n.index[-1].date())],
              "tickers": tradable, "criteria": CRITERIA, "benchmark_nifty": bench,
              "strategies": {}}
    for name, strat in STRATEGIES.items():
        r = simulate(data, strat, start)
        ok, fails = verdict(r)
        # PROBATION: failed approval, but positive per trade and ahead of the index.
        # Tradable only as a labelled experiment so forward results accumulate.
        status = ("APPROVED" if ok else
                  "PROBATION" if r.get("avg_R", -1) > 0 and r["cagr"] > bench["cagr"]
                  else "REJECTED")
        r.update({"status": status, "failed_criteria": fails,
                  "description": strat.describe})
        report["strategies"][name] = r
        print(f"{name:<20} {status:<9}  trades {r['trades']:>4}  "
              f"win {r.get('win_rate', 0)*100:>4.1f}%  avgR {r.get('avg_R', float('nan')):>+5.2f}  "
              f"t {r.get('t_stat', float('nan')):>5.2f}  "
              f"R first/last {r.get('avg_R_first_60pct', float('nan')):>+5.2f}/"
              f"{r.get('avg_R_last_40pct', float('nan')):>+5.2f}  "
              f"CAGR {r['cagr']*100:>+5.1f}%  maxDD {r['max_dd']*100:>4.1f}%  "
              f"hold {r.get('avg_hold', 0):.0f}d")
        for f in fails:
            print(f"    - {f}")
    out = Path(__file__).resolve().parent / "approved_strategies.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
