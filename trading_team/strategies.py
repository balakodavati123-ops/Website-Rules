"""Entry strategies, shared by the backtest lab and the live screen.

Each strategy is a fixed, published rule with no tuned parameters. A strategy
function takes a daily OHLCV DataFrame for one ticker and returns:
    score : Series, NaN where there is no entry signal that day (higher = stronger)
    exit  : boolean Series (exit at the next open when True), or None

The live screen only uses strategies listed as approved in
backtest/approved_strategies.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd


def _rsi(c: pd.Series, n: int) -> pd.Series:
    d = c.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def _base(df: pd.DataFrame):
    c = df["Close"]
    return c, c.rolling(50).mean(), c.rolling(200).mean()


def momentum_screen(df):
    """Uptrend, RSI 45-70, MACD histogram and 1-month return positive."""
    c, s50, s200 = _base(df)
    rsi = _rsi(c, 14)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    ok = ((c > s50) & (s50 > s200) & rsi.between(45, 70) & (hist > 0)
          & (c / c.shift(21) > 1))
    return (c / c.shift(63) - 1).where(ok), None


def pullback_in_uptrend(df):
    """Uptrend; price dipped to within 3% of the 50-day average in the last 5
    sessions and today closed above yesterday's high."""
    c, s50, s200 = _base(df)
    near = (df["Low"] / s50 - 1).rolling(5).min() <= 0.03
    ok = (c > s50) & (s50 > s200) & near & (c > df["High"].shift(1))
    return (c / c.shift(126) - 1).where(ok), None


def breakout_52w(df):
    """New 252-session closing high on volume at least 1.5x the 50-day average."""
    c, s50, s200 = _base(df)
    prior_high = c.shift(1).rolling(252).max()
    vol_ok = df["Volume"] >= 1.5 * df["Volume"].rolling(50).mean()
    ok = (c > prior_high) & vol_ok & (s50 > s200)
    return (c / c.shift(63) - 1).where(ok), None


def rsi2_dip(df):
    """Short-term dip in a long-term uptrend: above the 200-day average with
    RSI(2) below 10. Exit when the close is back above the 5-day average."""
    c, s50, s200 = _base(df)
    rsi2 = _rsi(c, 2)
    ok = (c > s200) & (rsi2 < 10)
    return (10 - rsi2).where(ok), c > c.rolling(5).mean()


def trend_ride(df):
    """Strong 12-month momentum (skipping the last month) in an uptrend, entered
    on a new 20-day closing high. No fixed target: exit on a close below the
    50-day average."""
    c, s50, s200 = _base(df)
    mom = c.shift(21) / c.shift(252) - 1
    ok = (c > s50) & (s50 > s200) & (mom > 0.20) & (c >= c.rolling(20).max())
    return mom.where(ok), c < s50


@dataclass(frozen=True)
class Strategy:
    name: str
    fn: Callable
    stop_pct: float            # initial stop below entry
    target_pct: float | None   # None = no fixed target (exit by signal or time)
    max_hold: int              # sessions
    describe: str


STRATEGIES = {s.name: s for s in [
    Strategy("momentum_screen", momentum_screen, 0.04, 0.20, 40,
             "Current desk screen: trend + RSI + MACD, 4% stop, 20% target"),
    Strategy("pullback_in_uptrend", pullback_in_uptrend, 0.04, 0.20, 40,
             "Buy a dip to the 50-day average in an uptrend, 4% stop, 20% target"),
    Strategy("breakout_52w", breakout_52w, 0.05, 0.20, 40,
             "52-week closing high on high volume, 5% stop, 20% target"),
    Strategy("rsi2_dip", rsi2_dip, 0.05, None, 10,
             "Short dip in an uptrend, exit on bounce, 5% stop, max 10 sessions"),
    Strategy("trend_ride", trend_ride, 0.05, None, 120,
             "12-month momentum, 5% stop, exit below the 50-day average"),
]}


VERDICT_FILE = Path(__file__).resolve().parents[1] / "backtest" / "approved_strategies.json"


def load_verdicts(path: str | Path | None) -> dict:
    """Lab results per strategy name; empty if the file is missing."""
    if path is None or not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text()).get("strategies", {})


def policy_compliant(strat: Strategy, rules) -> bool:
    """True if the strategy's exits fit the desk's stop and target ranges."""
    if strat.target_pct is None:
        return False
    return (rules.stop_loss_min_pct <= strat.stop_pct * 100 <= rules.stop_loss_max_pct
            and rules.target_min_pct <= strat.target_pct * 100 <= rules.target_max_pct)


def tradable(verdicts: dict, rules) -> dict[str, str]:
    """Strategy name -> status for strategies the live desk may trade:
    APPROVED or PROBATION in the lab, with exits that fit the risk policy."""
    out = {}
    for name, v in verdicts.items():
        strat = STRATEGIES.get(name)
        if strat and v.get("status") in ("APPROVED", "PROBATION") \
                and policy_compliant(strat, rules):
            out[name] = v["status"]
    return out


def live_signals(bars, names) -> list[tuple[str, float]]:
    """Strategies among `names` with an entry signal on the last bar."""
    if len(bars) < 260:
        return []
    df = pd.DataFrame({"Open": [b.open for b in bars], "High": [b.high for b in bars],
                       "Low": [b.low for b in bars], "Close": [b.close for b in bars],
                       "Volume": [b.volume for b in bars]})
    out = []
    for name in names:
        score, _ = STRATEGIES[name].fn(df)
        last = score.iloc[-1]
        if not np.isnan(last):
            out.append((name, float(last)))
    return out
