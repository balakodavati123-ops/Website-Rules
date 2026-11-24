"""A regime strategy for daily NIFTY options (buying only), chosen and tested walk-forward on real option prices.

Each trading day belongs to a regime cell known at 09:20: the volatility mode (MODE_1_QUIET, MODE_2_VOLATILE, MODE_3_HIGH_VOLATILITY, from India
VIX and the cross-market stress scores at 09:20) and days to expiry (0, 1-2, 3-4). For every cell the strategy picks one trade rule (structure,
entry time, target, stop) or SKIPS the day. The pick for a month uses only the months before it (expanding window, at least six months),
so every reported result is out of sample. A rule qualifies in a cell only with 15+ past trades there, a positive average after costs and a
profit factor of 1.1+; among those, the highest average minus one standard error wins (a cautious ranking); with none, the cell is skipped.
A second version picks by win rate instead, to show what chasing wins does to profit.
"""
from __future__ import annotations

import math
from collections import defaultdict

from ..reports.report import metrics

CELLS_DTE = {0: "0", 1: "1-2", 2: "1-2", 3: "3-4", 4: "3-4"}


def cell(mode: str, dte: int) -> str:
    return f"{mode} | DTE {CELLS_DTE.get(dte, '3-4')}"


def _lcb(xs: list[float]) -> float:
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m - sd / math.sqrt(n)


def choose(rows_by_cfg: dict, min_n: int = 15, min_pf: float = 1.1, by: str = "lcb") -> tuple[str | None, dict]:
    best, best_key, info = None, None, {}
    for cid, rr in rows_by_cfg.items():
        xs = [r["net_pnl_inr"] for r in rr]
        if len(xs) < min_n:
            continue
        w, l = sum(x for x in xs if x > 0), -sum(x for x in xs if x <= 0)
        pf = w / l if l > 0 else 9.9
        avg = sum(xs) / len(xs)
        if avg <= 0 or pf < min_pf:
            continue
        key = _lcb(xs) if by == "lcb" else sum(1 for x in xs if x > 0) / len(xs)
        if best_key is None or key > best_key:
            best, best_key, info = cid, key, {"n": len(xs), "avg": round(avg, 1), "pf": round(pf, 2), "win": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1)}
    return best, info


def walk_forward(rows: list[dict], min_months: int = 6, by: str = "lcb", min_n: int = 15, min_pf: float = 1.1) -> dict:
    day_cell, by_day_cfg = {}, defaultdict(dict)
    for r in rows:
        d = r["entry_timestamp_ist"][:10]
        if r["entry_window"] == "09:20" and d not in day_cell:
            day_cell[d] = cell(r["mode"], r["dte"])
        by_day_cfg[d][r["config_id"]] = r
    days = sorted(d for d in by_day_cfg if d in day_cell)
    months = sorted({d[:7] for d in days})
    taken, decisions = [], []
    for m in months[min_months:]:
        hist = [d for d in days if d[:7] < m]
        stats = defaultdict(lambda: defaultdict(list))
        for d in hist:
            for cid, r in by_day_cfg[d].items():
                stats[day_cell[d]][cid].append(r)
        picks = {c: choose(stats[c], min_n, min_pf, by) for c in stats}
        for d in (x for x in days if x[:7] == m):
            c = day_cell[d]
            cid, info = picks.get(c, (None, {}))
            decisions.append({"day": d, "cell": c, "rule": cid or "SKIP", "trained_on": info})
            if cid and cid in by_day_cfg[d]:
                taken.append(by_day_cfg[d][cid])
    final_stats = defaultdict(lambda: defaultdict(list))
    for d in days:
        for cid, r in by_day_cfg[d].items():
            final_stats[day_cell[d]][cid].append(r)
    final = {c: dict(zip(("rule", "trained_on"), choose(final_stats[c], min_n, min_pf, by))) for c in sorted(final_stats)}
    per_cell = defaultdict(list)
    for r in taken:
        per_cell[day_cell[r["entry_timestamp_ist"][:10]]].append(r)
    per_month = defaultdict(list)
    for r in taken:
        per_month[r["entry_timestamp_ist"][:7]].append(r["net_pnl_inr"])
    tested_days = [x for x in decisions]
    return {"out_of_sample": metrics(taken), "days_tested": len(tested_days), "days_traded": len(taken), "days_skipped": sum(1 for x in tested_days if x["rule"] == "SKIP"),
            "test_from": months[min_months] if len(months) > min_months else None, "test_to": months[-1] if months else None,
            "per_cell_out_of_sample": {c: metrics(v) for c, v in sorted(per_cell.items())},
            "per_month_out_of_sample": {k: {"trades": len(v), "net_inr": round(sum(v)), "won": sum(1 for x in v if x > 0)} for k, v in sorted(per_month.items())},
            "rules_today_from_all_data": final, "decisions": decisions[-30:]}


def fixed(rows: list[dict], cid: str, start_month: str) -> dict:
    return metrics([r for r in rows if r["config_id"] == cid and r["entry_timestamp_ist"][:7] >= start_month])
