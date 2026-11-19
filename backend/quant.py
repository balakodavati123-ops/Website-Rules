"""The quant agents: the numbers behind every entry, exit and verdict. Plain probability, no black box.

Each team has one. For a trade they work out how far the stop and target sit in units of the market's own noise over the trade's horizon,
the chance a random walk would reach the target before the stop (the baseline any real edge has to beat), the win rate needed to break even
after charges, the expected value with the team's real hit rate, and the Kelly fraction. For a team they test whether its hit rate on
targets is better than that random baseline (a z-score), plus profit factor, average and worst run of losses. Nothing here trades.
"""
from __future__ import annotations

import math


def sigma_bars(closes: list[float], horizon: int = 1) -> float | None:
    """Standard deviation of returns over `horizon` bars, in percent, from 1-bar log returns (square-root-of-time scaling)."""
    r = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]
    if len(r) < 10:
        return None
    m = sum(r) / len(r)
    sd = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1))
    return sd * math.sqrt(max(horizon, 1)) * 100


def baseline_p(stop_dist: float, target_dist: float) -> float:
    """Chance a driftless random walk touches the target before the stop: stop / (stop + target). A 1.5R target gives 40%."""
    return stop_dist / (stop_dist + target_dist) if stop_dist > 0 and target_dist > 0 else 0.0


def breakeven_p(risk: float, reward: float, cost: float = 0.0) -> float:
    """Win rate needed to break even when a win pays `reward - cost` and a loss costs `risk + cost`."""
    w, l = reward - cost, risk + cost
    return l / (w + l) if w > 0 and l > 0 else 1.0


def kelly(p: float, b: float) -> float:
    """Kelly fraction for win probability p and payoff ratio b (reward / risk); below zero means no bet."""
    return p - (1 - p) / b if b > 0 else -1.0


def trade_numbers(entry: float, stop: float, target: float | None, qty: float, cost: float = 0.0, sigma_pct: float | None = None, team_hit: float | None = None) -> dict:
    """The quant note for one trade."""
    if not (entry and stop):
        return {}
    sd = abs(entry - stop)
    td = abs((target or entry) - entry)
    out = {"risk_rs": round(sd * qty, 2)}
    if td > 0:
        p0 = baseline_p(sd, td)
        b = td / sd
        be = breakeven_p(sd * qty, td * qty, cost)
        p = team_hit if team_hit is not None else p0
        out.update(reward_rs=round(td * qty, 2), rr=round(b, 2), base_p=round(p0, 3), breakeven_p=round(be, 3), used_p=round(p, 3), p_source="team record" if team_hit is not None else "random-walk baseline",
                   ev_rs=round(p * (td * qty - cost) - (1 - p) * (sd * qty + cost), 2), kelly=round(kelly(p, b), 3))
    if sigma_pct:
        out["stop_sigma"] = round(sd / entry * 100 / sigma_pct, 2)
        if td:
            out["target_sigma"] = round(td / entry * 100 / sigma_pct, 2)
        notes = []
        if out["stop_sigma"] < 1.0:
            notes.append("stop is inside one standard deviation of normal noise for the holding time: likely to be hit by chance")
        if td and out.get("target_sigma", 0) > 2.5:
            notes.append("target is more than 2.5 standard deviations away for the holding time: unlikely to be reached in time")
        out["warnings"] = notes
    return out


def team_numbers(trades: list[dict]) -> dict:
    """Record of a team's closed trades: hit rate on targets against the random baseline, profit factor, average, worst losing run."""
    closed = [t for t in trades if t.get("status") in ("WIN", "LOSS")]
    pnl = [float(t.get("pnl_rs") or 0) for t in closed]
    n = len(closed)
    if not n:
        return {"n": 0}
    wins, losses = [x for x in pnl if x > 0], [x for x in pnl if x <= 0]
    run = worst = 0
    for x in pnl:
        run = run + 1 if x <= 0 else 0
        worst = max(worst, run)
    out = {"n": n, "win_rate": round(len(wins) / n * 100, 1), "avg_rs": round(sum(pnl) / n, 2), "net_rs": round(sum(pnl), 2), "worst_run": worst,
           "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None}
    geo = [t for t in closed if t.get("stop") and t.get("target_px") and t.get("entry")]
    if len(geo) >= 5:
        p0 = [baseline_p(abs(float(t["entry"]) - float(t["stop"])), abs(float(t["target_px"]) - float(t["entry"]))) for t in geo]
        hits = sum(1 for t in geo if t.get("why") == "target")
        var = sum(p * (1 - p) for p in p0)
        out.update(target_hits=hits, expected_hits=round(sum(p0), 1), edge_z=round((hits - sum(p0)) / math.sqrt(var), 2) if var > 0 else None, hit_rate=round(hits / len(geo), 3))
    return out
