"""Anti-hallucination and data-freshness guards.

These checks run in code, after the LLMs reply, so a model cannot pass an
invented figure or an unchecked trade downstream.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .models import Bar

# A minus sign counts only at the start or after a space/bracket, so the "3" in
# "1-3 months" is not read as -3.
NUMBER_RE = re.compile(r"(?:(?<=^)|(?<=[\s(\[]))-?\d+(?:\.\d+)?|(?<![A-Za-z_\d.])\d+(?:\.\d+)?")
# Western (1,234,567) and Indian (12,34,567) grouping; the last group has 3 digits,
# so a parameter list like "12,26,9" is left alone.
THOUSANDS_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{2,3})*,\d{3}(?!\d|,\d)")


def _numbers(text: str) -> list[str]:
    text = THOUSANDS_RE.sub(lambda m: m.group(0).replace(",", ""), text or "")
    return NUMBER_RE.findall(text)

# Numbers the agents may always state: rule parameters and indicator settings.
# These are not market data. Kept deliberately short.
ALWAYS_ALLOWED = {
    0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 15.0, 30.0, 100.0,   # rule parameters
    9.0, 12.0, 14.0, 20.0, 26.0, 50.0, 52.0, 200.0,     # indicator periods and '52-week'
    70.0,                                               # RSI overbought line
}


def flatten_numbers(obj: Any, out: set[float] | None = None) -> set[float]:
    """Every numeric value in a nested context, as floats."""
    if out is None:
        out = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            flatten_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            flatten_numbers(v, out)
    elif isinstance(obj, str):
        for m in _numbers(obj):
            out.add(float(m))
    return out


def ungrounded_numbers(text: str, context: Any, tol: float = 0.011) -> list[str]:
    """Numbers quoted in `text` that do not appear in `context`.

    A figure matches if it equals a context value to within `tol`, or it is
    one of the always-allowed rule constants. Percentages are compared both
    raw and as a fraction, so 0.05 and 5% both match 5.
    """
    allowed = flatten_numbers(context) | ALWAYS_ALLOWED
    allowed |= {round(v * 100, 6) for v in list(allowed)}  # fraction -> percent
    bad: list[str] = []
    for token in _numbers(text):
        v = float(token)
        if any(abs(v - a) <= tol * max(1.0, abs(a)) for a in allowed):
            continue
        bad.append(token)
    return bad


def is_fresh(bars: list[Bar], run_date: date, max_lag_days: int = 4) -> bool:
    """True if the last bar is recent enough to act on.

    Four calendar days covers a weekend plus one holiday. Anything older is
    stale and must be treated as unverified.
    """
    if not bars:
        return False
    return run_date - bars[-1].day <= timedelta(days=max_lag_days)


def validate_pm_output(proposal: dict, candidate_tickers: set[str]) -> list[str]:
    """Strict schema check on the portfolio manager's JSON. Returns problems."""
    problems: list[str] = []
    action = proposal.get("action")
    if action not in ("BUY", "NO_TRADE"):
        problems.append(f"action must be BUY or NO_TRADE, got {action!r}")
    if action == "BUY":
        if proposal.get("ticker") not in candidate_tickers:
            problems.append("ticker must be one of the candidates")
        for key in ("stop_pct", "target_pct", "confidence"):
            if not isinstance(proposal.get(key), (int, float)) or isinstance(proposal.get(key), bool):
                problems.append(f"{key} must be a number")
        conf = proposal.get("confidence")
        if isinstance(conf, (int, float)) and not 0 <= conf <= 1:
            problems.append("confidence must be between 0 and 1")
    if not isinstance(proposal.get("rationale", ""), str):
        problems.append("rationale must be a string")
    return problems


def grounding_report(texts: dict[str, str], context: Any) -> dict[str, list[str]]:
    """Ungrounded figures per field, empty lists omitted."""
    out = {}
    for name, text in texts.items():
        bad = ungrounded_numbers(text, context)
        if bad:
            out[name] = bad
    return out
