"""Quant agent training: the walk-forward set-up, the state/action/reward definitions, and the permission gate. No training runs here.

Nothing in this module fits weights, changes a live threshold or sends an order unless the CEO's approval token is present:
  APPROVE_AGENT_TRAINING     train or tune the decision policy on the backtest dataset
  APPROVE_PAPER_EXECUTION    let the tuned policy drive the paper-trading desk
The approval is read from the environment variable QUANT_APPROVALS or the file quant/APPROVALS (one token per line), so it can only come from
someone with write access to the repository or its settings.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ACTIONS = ("ENTER_STRADDLE", "HOLD", "EXIT_TP", "EXIT_SL", "SKIP_NO_EDGE")
STATE_FEATURES = ("dte", "entry_window", "mode", "sigma_iv", "sigma_eff", "S_IN_Bank", "S_US_Macro", "S_Asia_FX", "morning_move_pct", "gap_pct", "vix_change_pct",
                  "premium_vs_expected_range", "minutes_since_entry", "unrealised_return_pct", "mae_so_far_pct", "mfe_so_far_pct")
REWARD = "net_pnl_inr after charges and slippage at exit; 0 for SKIP_NO_EDGE; no reward shaping that could reward risk-taking"


class PermissionDenied(PermissionError):
    pass


def approved(token: str, root: Path = Path("quant")) -> bool:
    env = {x.strip() for x in os.environ.get("QUANT_APPROVALS", "").split(",") if x.strip()}
    f = root / "APPROVALS"
    filed = {x.strip() for x in f.read_text().splitlines() if x.strip()} if f.exists() else set()
    return token in env | filed


def require(token: str, root: Path = Path("quant")) -> None:
    if not approved(token, root):
        raise PermissionDenied(f"{token} has not been given. Training and execution stay off until the CEO approves.")


@dataclass
class WalkForward:
    """Expanding-window splits by expiry month: train on everything before a month, validate on that month, test on the months after the
    last validation month; no row of a later expiry ever reaches an earlier fold."""
    min_train_months: int = 6

    def splits(self, months: list[str]) -> list[tuple[list[str], str]]:
        months = sorted(set(months))
        return [(months[:i], months[i]) for i in range(self.min_train_months, len(months))]


def train(rows: list[dict], root: Path = Path("quant")) -> None:
    require("APPROVE_AGENT_TRAINING", root)
    raise NotImplementedError("Training is approved but not yet implemented: it will fit only after the CEO reviews the backtest report.")
