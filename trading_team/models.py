"""Shared data types for the trading team."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Bar:
    """One daily OHLCV bar. Prices are raw (unadjusted) closes."""

    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class DataPoint:
    """A single datum plus where it came from and whether it was confirmed.

    `verified` is True only when a configured source returned the value and it
    passed sanity checks. Anything else is reported as "Data Unverified".
    """

    value: Any = None
    source: str | None = None
    verified: bool = False
    note: str = ""


@dataclass
class Snapshot:
    """Everything the data agent could gather for one ticker on one day."""

    ticker: str
    as_of: date
    bars: list[Bar] = field(default_factory=list)
    points: dict[str, DataPoint] = field(default_factory=dict)

    def unverified_items(self) -> list[str]:
        items: list[str] = []
        if not self.bars:
            items.append("price history")
        for name, point in self.points.items():
            if not point.verified:
                suffix = f" ({point.note})" if point.note else ""
                items.append(f"{name}{suffix}")
        return items


@dataclass
class Recommendation:
    """The final output of one daily run. action is BUY or NO_TRADE."""

    run_date: date
    action: str
    ticker: str | None = None
    entry_price: float | None = None
    stop_pct: float | None = None
    target_pct: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    confidence: float | None = None
    rationale: str = ""
    risk_notes: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)

    @property
    def is_trade(self) -> bool:
        return self.action == "BUY" and self.ticker is not None
