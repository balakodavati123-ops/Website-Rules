"""The strategy lab: every strategy version moves through one pipeline and must pass the validation gate before real money.

Stages: PROPOSED (an improved version the COO asked the CEO for) -> BUILT (code running on paper, under 10 closed trades) -> TESTED (10 to 29)
-> REVIEWED, which ends in APPROVED (every check passed) or INVESTIGATE (some failed); REJECTED when the record paused it or the CEO retired it.
The checks are run on the paper record, oldest trade first, never on a single backtest: enough trades, profit after charges, profit after
doubling the cost assumption, the most recent 30% of trades (out of sample) still profitable, target hits better than chance, profitable on
most days, and a losing streak within limits. Passing is a prerequisite, not proof of future profit. Only APPROVED strategies may reach the
execution gateway. Nothing here trades.
"""
from __future__ import annotations

from collections import Counter

import quant as Q

EXTRA_COST = {"EQUITY": 20.0, "FNO": 80.0, "COMMODITY": 40.0, "CRYPTO": 20.0}      # one more round trip of charges per trade, assumed
STAGES = ["PROPOSED", "BUILT", "TESTED", "APPROVED", "INVESTIGATE", "REJECTED"]


def _key(t: dict) -> tuple:
    return (str(t.get("day")), str(t.get("closed") or t.get("opened") or ""))


def checks(trades: list[dict]) -> list[dict]:
    closed = sorted([t for t in trades if t.get("status") in ("WIN", "LOSS")], key=_key)
    n = len(closed)
    pnl = [float(t.get("pnl_rs") or 0) for t in closed]
    net = sum(pnl)
    extra = sum(EXTRA_COST.get(str(t.get("desk")), 20.0) for t in closed)
    k = int(n * 0.7)
    oos = pnl[k:] if n >= 10 else []
    rec = Q.team_numbers(closed)
    days: dict = {}
    for t, p in zip(closed, pnl):
        days[t.get("day")] = days.get(t.get("day"), 0.0) + p
    good_days = sum(1 for v in days.values() if v > 0)
    c = lambda name, ok, value, need: {"name": name, "ok": ok, "value": value, "need": need}
    return [
        c("Enough trades", n >= 30, f"{n} closed", "30 or more"),
        c("Profit after charges", (net > 0) if n else None, f"₹{net:,.0f}", "above ₹0"),
        c("Survives double costs", (net - extra > 0) if n else None, f"₹{net - extra:,.0f}", "above ₹0 with one more round trip of charges per trade"),
        c("Out of sample", (sum(oos) > 0) if oos else None, f"₹{sum(oos):,.0f} on the latest {len(oos)}" if oos else "needs 10 trades", "the most recent 30% of trades still profitable"),
        c("Beats chance", (rec["edge_z"] >= 1.0) if rec.get("edge_z") is not None else None,
          f"targets {rec.get('target_hits')} vs {rec.get('expected_hits')} by chance (z {rec.get('edge_z')})" if rec.get("edge_z") is not None else "needs 5 trades with a stop and target", "z of 1.0 or more"),
        c("Profitable on most days", (good_days / len(days) >= 0.5) if len(days) >= 5 else None, f"{good_days} of {len(days)} days", "half the days or more, over 5+ days"),
        c("Losing streak in limits", (rec.get("worst_run", 0) <= 8) if n else None, f"worst run {rec.get('worst_run', 0)}", "8 losses in a row at most"),
    ]


def stage_of(name: str, n: int, cks: list[dict], verdict: str, retired: list, resumed: list) -> str:
    if name in retired or (verdict == "PAUSED" and name not in resumed):
        return "REJECTED"
    if n < 10:
        return "BUILT"
    if n < 30:
        return "TESTED"
    return "APPROVED" if all(c["ok"] for c in cks) else "INVESTIGATE"


def lessons(trades: list[dict]) -> list[str]:
    closed = [t for t in trades if t.get("status") in ("WIN", "LOSS")]
    if len(closed) < 10:
        return []
    why = Counter(str(t.get("why") or "exit").split(":")[0] for t in closed)
    top, cnt = why.most_common(1)[0]
    out = [f"{cnt} of {len(closed)} trades ended at the {top}."]
    wins, losses = [float(t["pnl_rs"]) for t in closed if float(t.get("pnl_rs") or 0) > 0], [float(t["pnl_rs"]) for t in closed if float(t.get("pnl_rs") or 0) <= 0]
    if wins and losses:
        out.append(f"Average win ₹{sum(wins) / len(wins):,.0f} against average loss ₹{-sum(losses) / len(losses):,.0f}.")
    return out


def build(trades: list[dict], stats: list[dict], co_state: dict, team_of, gw: dict | None = None) -> dict:
    """trades: every trade (open and closed, all days); stats: strategy_stats rows; co_state: the company state (retired, resumed, variants, requests)."""
    by: dict = {}
    for t in trades:
        by.setdefault(str(t.get("strategy")), []).append(t)
    vst = {s["strategy"]: s for s in stats}
    retired, resumed = co_state.get("retired") or [], co_state.get("resumed") or []
    rows = []
    for name, T in sorted(by.items()):
        cks = checks(T)
        n = sum(t.get("status") in ("WIN", "LOSS") for t in T)
        net = sum(float(t.get("pnl_rs") or 0) for t in T if t.get("status") in ("WIN", "LOSS"))
        st = stage_of(name, n, cks, (vst.get(name) or {}).get("verdict", ""), retired, resumed)
        rows.append({"strategy": name, "team": team_of(T[0]), "desk": T[0].get("desk"), "stage": st, "closed": n, "open": sum(t.get("status") == "OPEN" for t in T), "net_rs": round(net, 2),
                     "win_rate": round(sum(t.get("status") == "WIN" for t in T) / n * 100, 1) if n else None, "since": min(str(t.get("day")) for t in T),
                     "passed": sum(1 for c in cks if c["ok"]), "checks": cks, "lessons": lessons(T)})
    for r in co_state.get("requests") or []:
        if r.get("variant") and r.get("status") == "pending":
            rows.append({"strategy": r["variant"]["name"], "team": r.get("team"), "desk": None, "stage": "PROPOSED", "closed": 0, "open": 0, "net_rs": 0.0, "win_rate": None,
                         "since": r.get("created"), "passed": 0, "checks": [], "lessons": [r["variant"].get("why", "")], "request": r["id"]})
    order = {s: i for i, s in enumerate(STAGES)}
    rows.sort(key=lambda r: (order.get(r["stage"], 9), -r["closed"]))
    counts = Counter(r["stage"] for r in rows)
    return {"stages": [{"stage": s, "n": counts.get(s, 0)} for s in STAGES], "strategies": rows,
            "approved": [r["strategy"] for r in rows if r["stage"] == "APPROVED"],
            "experiments": [{"team": k, **v} for k, v in (co_state.get("variants") or {}).items()],
            "rule": "Only APPROVED strategies may reach the execution gateway; passing is a prerequisite, not proof of future profit."}
