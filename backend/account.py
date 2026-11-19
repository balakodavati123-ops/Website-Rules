"""The paper account: one pool of money for every desk. Rupees, not points.

Starts at START. Equity = start + closed profit + open profit. A trade ties up its cost (shares and crypto) or its
margin (futures and options). Each kind of trade gets a share of the account, so no desk can spend what the others need.
"""
from __future__ import annotations

START = 100000.0
# Limits, not reservations: no desk may tie up more than its share, and every desk is also held to the cash actually free.
# Real broker margins on this account size: one NIFTY spread needs about Rs 38,000, a crude oil mini lot about Rs 25,000, so F&O and commodities get the larger limits.
BUDGET = {"swing": 0.22, "signal": 0.05, "intraday": 0.12, "scalp": 0.20, "FNO": 0.50, "COMMODITY": 0.25, "CRYPTO": 0.05}
LABEL = {"swing": "Swing (daily bars)", "signal": "Signal desk", "intraday": "Intraday equities", "scalp": "Scalping (intraday margin)", "FNO": "F&O margin", "COMMODITY": "Commodities margin", "CRYPTO": "Crypto"}


def bucket(t: dict) -> str:
    if t["desk"] == "EQUITY":
        return "swing" if t.get("opened") == "swing" else "signal" if t.get("opened") == "signal" else "scalp" if str(t.get("strategy", "")).startswith("scalp") else "intraday"
    return t["desk"]


def invested(t: dict) -> float:
    """What the position ties up: cost for shares, the notional put in for crypto, margin for futures and options."""
    try:
        if t["desk"] == "EQUITY":
            return float(t["entry"] or 0) * float(t["qty"] or 0) / (float(t.get("leverage") or 1) or 1)       # intraday margin trades tie up a fraction of the stock's value
        if t["desk"] == "CRYPTO":
            return float(t["qty"] or 0)
        return float(t.get("margin_rs") or 0)
    except (TypeError, ValueError):
        return 0.0


def summary(trades: list[dict]) -> dict:
    opn = [t for t in trades if t["status"] == "OPEN"]
    closed = [t for t in trades if t["status"] in ("WIN", "LOSS")]
    realised = sum(float(t["pnl_rs"] or 0) for t in closed)
    unreal = sum(float(t["pnl_rs"] or 0) for t in opn)
    used = {k: 0.0 for k in BUDGET}
    for t in opn:
        used[bucket(t)] += invested(t)
    in_use = sum(used.values())
    equity = START + realised + unreal
    return {"start": START, "realised": round(realised, 2), "unrealised": round(unreal, 2), "equity": round(equity, 2), "in_use": round(in_use, 2), "cash": round(equity - in_use, 2),
            "pnl": round(equity - START, 2), "pnl_pct": round((equity / START - 1) * 100, 2), "open": len(opn), "closed": len(closed),
            "buckets": {k: {"label": LABEL[k], "budget": round(BUDGET[k] * START), "used": round(used[k]), "room": round(max(0.0, min(BUDGET[k] * START - used[k], equity - in_use)))} for k in BUDGET}}


class Room:
    """A desk's room as a one-item list a desk can read and spend from (room[0] -= margin). Every desk also draws on one shared pool of free
    cash, so two desks opening trades in the same moment cannot spend the same rupees."""

    def __init__(self, own: float, cash: list):
        self.own, self.cash = float(own), cash

    def __getitem__(self, i: int) -> float:
        return max(0.0, min(self.own, self.cash[0]))

    def __setitem__(self, i: int, v: float) -> None:
        spent = self[0] - v
        self.own -= spent
        self.cash[0] -= spent


def rooms(trades: list[dict]) -> dict:
    """Room left per bucket, each limited by its own share and by the cash everyone shares."""
    s = summary(trades)
    cash = [max(0.0, s["cash"])]
    return {k: Room(v["room"], cash) for k, v in s["buckets"].items()}
