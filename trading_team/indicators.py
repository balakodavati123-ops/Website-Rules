"""Deterministic technical indicators. The LLM analysts read these numbers;
they never compute them, so the figures are reproducible."""
from __future__ import annotations

import math
from typing import Sequence

from .models import Bar


def sma(values: Sequence[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _ema_series(values: Sequence[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out: list[float] = []
    prev: float | None = None
    for v in values:
        prev = v if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(closes: Sequence[float], n: int = 14) -> float | None:
    """Wilder's RSI."""
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for prev, cur in zip(closes, closes[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        avg_gain = (avg_gain * (n - 1) + g) / n
        avg_loss = (avg_loss * (n - 1) + l) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def macd(closes: Sequence[float]) -> tuple[float, float, float] | None:
    """Returns (macd line, signal line, histogram) at the last bar."""
    if len(closes) < 35:
        return None
    line = [a - b for a, b in zip(_ema_series(closes, 12), _ema_series(closes, 26))]
    signal = _ema_series(line, 9)
    return line[-1], signal[-1], line[-1] - signal[-1]


def atr(bars: Sequence[Bar], n: int = 14) -> float | None:
    if len(bars) < n + 1:
        return None
    trs = []
    for prev, cur in zip(bars, bars[1:]):
        trs.append(max(cur.high - cur.low,
                       abs(cur.high - prev.close),
                       abs(cur.low - prev.close)))
    value = sum(trs[:n]) / n
    for tr in trs[n:]:
        value = (value * (n - 1) + tr) / n
    return value


def realized_vol(closes: Sequence[float], n: int = 20) -> float | None:
    """Annualised standard deviation of daily log returns over the last n days."""
    if len(closes) < n + 1:
        return None
    rets = [math.log(b / a) for a, b in zip(closes[-n - 1:-1], closes[-n:])]
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return math.sqrt(var) * math.sqrt(252)


def technical_summary(bars: Sequence[Bar]) -> dict:
    """All indicators the technical analyst and the screen use."""
    closes = [b.close for b in bars]
    last = closes[-1]
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)

    if sma50 is not None and sma200 is not None:
        if last > sma50 > sma200:
            trend = "uptrend"
        elif last < sma50 < sma200:
            trend = "downtrend"
        else:
            trend = "mixed"
    elif sma50 is not None:
        trend = "uptrend" if last > sma50 else "downtrend" if last < sma50 else "mixed"
    else:
        trend = "insufficient history for trend"

    m = macd(closes)
    atr14 = atr(bars, 14)
    vol = realized_vol(closes, 20)
    recent = bars[-20:]
    ret_1m = (last / closes[-21] - 1) * 100 if len(closes) > 21 else None
    ret_3m = (last / closes[-63] - 1) * 100 if len(closes) > 63 else None

    def r(x, nd=2):
        return None if x is None else round(x, nd)

    def pct_vs(level):
        return None if not level else round((last / level - 1) * 100, 1)

    support, resistance = min(b.low for b in recent), max(b.high for b in recent)

    return {
        "last_close": r(last),
        "last_date": bars[-1].day.isoformat(),
        "sma50": r(sma50),
        "sma200": r(sma200),
        "trend": trend,
        "rsi14": r(rsi(closes, 14), 1),
        "macd": r(m[0], 3) if m else None,
        "macd_signal": r(m[1], 3) if m else None,
        "macd_hist": r(m[2], 3) if m else None,
        "atr14_pct_of_price": r(atr14 / last * 100) if atr14 else None,
        "realized_vol_20d_ann": r(vol, 3),
        "support_20d": r(min(b.low for b in recent)),
        "resistance_20d": r(max(b.high for b in recent)),
        # Distances are precomputed so analysts quote them instead of deriving
        # their own figures, which the grounding check would reject.
        "pct_vs_sma50": pct_vs(sma50),
        "pct_vs_sma200": pct_vs(sma200),
        "pct_above_support_20d": pct_vs(support),
        "pct_below_resistance_20d": round((1 - last / resistance) * 100, 1),
        "atr14": r(atr14),
        "high_52w": r(max(b.high for b in bars[-252:])),
        "low_52w": r(min(b.low for b in bars[-252:])),
        "pct_below_52w_high": round((1 - last / max(b.high for b in bars[-252:])) * 100, 1),
        "volume_vs_50d_avg": (round(bars[-1].volume / (sum(b.volume for b in bars[-50:]) / 50), 2)
                              if len(bars) >= 50 and sum(b.volume for b in bars[-50:]) else None),
        "return_1m_pct": r(ret_1m, 1),
        "return_3m_pct": r(ret_3m, 1),
    }


def screen_score(tech: dict) -> float:
    """Simple, explainable ranking used only to choose which tickers get
    the full (LLM-heavy) analysis. It is not a trade signal."""
    score = 0.0
    score += {"uptrend": 2.0, "mixed": 0.0, "downtrend": -2.0}.get(tech["trend"], 0.0)
    rsi_v = tech.get("rsi14")
    if rsi_v is not None and 45 <= rsi_v <= 70:
        score += 1.0
    if (tech.get("macd_hist") or 0) > 0:
        score += 1.0
    if (tech.get("return_1m_pct") or 0) > 0:
        score += 1.0
    return score
