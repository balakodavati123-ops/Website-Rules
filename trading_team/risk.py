"""Risk manager: applies the house rules and can veto any proposal.

Rules (see config.RiskRules):
  * stop-loss between 3% and 5% below entry (out-of-range values are clamped)
  * target between 15% and 30% above entry (out-of-range values are clamped)
  * at most one idea a day
  * stay in cash if India VIX is above the limit, if it is unavailable, or if
    the stock's own realised volatility is too high
  * no trade without a verified price history
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import RiskRules
from .models import DataPoint


@dataclass
class RiskReview:
    approved: bool
    ticker: str | None = None
    stop_pct: float | None = None
    target_pct: float | None = None
    notes: list[str] = field(default_factory=list)


class RiskManager:
    def __init__(self, rules: RiskRules):
        self.rules = rules

    def review(self, proposal: dict, candidates: dict[str, "CandidateRisk"],
               market: dict[str, DataPoint]) -> RiskReview:
        r = self.rules
        notes: list[str] = []

        if str(proposal.get("action", "")).upper() != "BUY":
            return RiskReview(False, notes=["portfolio manager chose NO_TRADE"])

        ticker = proposal.get("ticker")
        if r.max_ideas_per_day < 1:
            return RiskReview(False, notes=["max_ideas_per_day is set to zero"])

        vix = market.get("india_vix")
        if vix is None or vix.value is None:
            return RiskReview(False, notes=[
                "India VIX unavailable: volatility cannot be checked, staying in cash"])
        if vix.value > r.max_india_vix:
            return RiskReview(False, notes=[
                f"India VIX {vix.value:.1f} is above {r.max_india_vix}: staying in cash"])

        cand = candidates.get(ticker)
        if cand is None:
            return RiskReview(False, notes=[f"{ticker!r} is not a candidate in this run"])
        if not cand.price_verified:
            return RiskReview(False, notes=[f"{ticker}: price history is unverified"])
        if cand.realized_vol is None:
            return RiskReview(False, notes=[f"{ticker}: volatility unavailable"])
        if cand.realized_vol > r.max_stock_realized_vol:
            return RiskReview(False, notes=[
                f"{ticker}: 20-day realised volatility {cand.realized_vol:.0%} is above "
                f"{r.max_stock_realized_vol:.0%}"])

        stop = self._clamp("stop-loss", proposal.get("stop_pct"),
                           r.stop_loss_min_pct, r.stop_loss_max_pct, notes)
        target = self._clamp("target", proposal.get("target_pct"),
                             r.target_min_pct, r.target_max_pct, notes)

        return RiskReview(True, ticker=ticker, stop_pct=stop, target_pct=target,
                          notes=notes)

    @staticmethod
    def _clamp(label, value, lo, hi, notes) -> float:
        if value is None:
            mid = round((lo + hi) / 2, 2)
            notes.append(f"no {label} given; applied the midpoint {mid}%")
            return mid
        try:
            v = float(value)
        except (TypeError, ValueError):
            mid = round((lo + hi) / 2, 2)
            notes.append(f"{label} was not a number; applied the midpoint {mid}%")
            return mid
        clamped = min(max(v, lo), hi)
        if clamped != v:
            notes.append(f"{label} {v}% adjusted to {clamped}% (allowed {lo}-{hi}%)")
        return clamped


@dataclass
class CandidateRisk:
    """The facts the risk manager needs about one candidate."""
    price_verified: bool
    realized_vol: float | None
