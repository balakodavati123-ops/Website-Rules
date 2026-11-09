"""Settings and the risk rules the risk manager enforces."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RiskRules:
    stop_loss_min_pct: float = 3.0
    stop_loss_max_pct: float = 5.0
    target_min_pct: float = 15.0
    target_max_pct: float = 30.0
    max_ideas_per_day: int = 1
    # Stay in cash when the market is volatile. India VIX is the market gauge.
    max_india_vix: float = 20.0
    # Stay out of a single stock whose 20-day realised volatility is this high.
    max_stock_realized_vol: float = 0.60
    max_hold_trading_days: int = 30


@dataclass(frozen=True)
class Settings:
    model: str = "claude-sonnet-5-5"
    candidates_per_run: int = 5
    history_days: int = 400
    ledger_path: str = "data/ledger.sqlite"
    report_dir: str = "reports"
    rules: RiskRules = field(default_factory=RiskRules)
