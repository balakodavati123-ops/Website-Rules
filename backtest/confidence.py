"""How sure can we be that each strategy has a positive edge?

"99% confidence" has a precise meaning here: the data should leave less than a 1%
chance that the true average result per trade (in R, where 1R = the amount risked)
is zero or negative. This is NOT a 99% win rate. Even a great strategy loses
many individual trades.

Three views of the same trade list, from most to least generous:
  naive    one-sided t-test treating every trade as independent
  cluster  month-block bootstrap: resamples whole months, because trades taken in the
           same month share the same market and are not independent
  adjusted the cluster result corrected for having tried several strategies
           (the best of N tries looks better than it is): Sidak correction

Usage: python backtest/confidence.py [--cache DIR] [--years 5]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from strategy_lab import add_earnings, fetch_universe, simulate  # noqa: E402
from trading_team.strategies import STRATEGIES  # noqa: E402


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def analyse(tr: pd.DataFrame, dates: pd.DatetimeIndex, n_tests: int, seed: int = 11) -> dict:
    R = tr.R.to_numpy()
    n = len(R)
    mean, sd = R.mean(), R.std(ddof=1)
    se = sd / math.sqrt(n)
    t = mean / se
    p_naive = 1 - norm_cdf(t)                       # one-sided: P(no edge | data)
    month = pd.Series(dates[tr.entry_i.to_numpy()]).dt.to_period("M").astype(str).to_numpy()
    groups = {m: R[month == m] for m in np.unique(month)}
    keys = list(groups)
    rng = np.random.default_rng(seed)
    means = np.empty(20000)
    for i in range(means.size):
        pick = rng.choice(len(keys), len(keys))
        allr = np.concatenate([groups[keys[j]] for j in pick])
        means[i] = allr.mean()
    p_cluster = float((means <= 0).mean())
    p_adj = 1 - (1 - p_cluster) ** n_tests          # chance the best of N tries looks this good by luck
    lo99, hi99 = np.percentile(means, [0.5, 99.5])
    # trades needed for 99% (t = 2.326) if the true mean and sd stayed as measured
    need = math.ceil((2.326 * sd / mean) ** 2) if mean > 0 else None
    return {"trades": n, "avg_R": mean, "t_stat": t, "confidence_naive": 1 - p_naive,
            "confidence_cluster": 1 - p_cluster, "confidence_adjusted": 1 - p_adj,
            "avgR_99pct_range": (float(lo99), float(hi99)), "months": len(keys),
            "trades_needed_for_99": need}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--cache", type=Path, default=None)
    args = ap.parse_args()
    data = fetch_universe(args.years, args.cache)
    add_earnings(data, args.cache)
    cal = data["^NSEI"].index
    start = cal[-1] - pd.DateOffset(years=args.years)
    n_tests = len(STRATEGIES)
    print(f"{n_tests} strategies tested; trades from {start.date()} to {cal[-1].date()}\n")
    results = {}
    print(f"{'strategy':<22}{'trades':>7}{'avg R':>8}{'naive':>9}{'cluster':>9}{'adjusted':>10}"
          f"{'99% range of true avg R':>28}{'trades for 99%':>16}")
    for name, strat in STRATEGIES.items():
        r = simulate(data, strat, start)
        tr = r["trade_table"]
        if len(tr) < 30:
            print(f"{name:<22}{len(tr):>7}  too few trades")
            continue
        a = analyse(tr, cal, n_tests)
        results[name] = {**a, "avgR_99pct_range": list(a["avgR_99pct_range"])}
        lo, hi = a["avgR_99pct_range"]
        need = a["trades_needed_for_99"]
        print(f"{name:<22}{a['trades']:>7}{a['avg_R']:>+8.2f}{a['confidence_naive']*100:>8.1f}%"
              f"{a['confidence_cluster']*100:>8.1f}%{a['confidence_adjusted']*100:>9.1f}%"
              f"{'  %+.2f to %+.2f' % (lo, hi):>28}{(str(need) if need else 'n/a'):>16}")
    (Path(__file__).resolve().parent / "confidence_results.json").write_text(
        __import__("json").dumps(results, indent=2))
    print("\nconfidence = chance the true average result per trade is above zero.")
    print("A strategy is 'close' to 99% only if the adjusted column reaches about 99%.")


if __name__ == "__main__":
    main()
