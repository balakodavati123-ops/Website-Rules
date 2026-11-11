"""Order tickets: everything needed to place a trade by hand in a few taps.

This module never places an order and has no way to. It turns a recommendation
into exact numbers and a checklist, and re-checks them against a live price so a
stale plan is not acted on.

Sizing follows the desk's rules: risk a fixed share of equity (0.5% in Caution,
1% in Normal) divided by the per-share stop distance, capped at 30% of equity in
one position and 4% of equity in total open risk.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def _tick(x: float, tick: float, up: bool = False) -> float:
    """Round to the exchange tick size (0.05 for most stocks)."""
    n = x / tick
    n = math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)
    return round(n * tick, 2)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Ticket:
    ticker: str
    status: str                  # READY, WAITING or DO NOT TRADE
    qty: int
    entry_limit: float
    stop_trigger: float
    stop_limit: float
    target: float
    position_value: float
    pct_of_equity: float
    risk_rs: float
    reward_rs: float
    stop_pct: float
    target_pct: float
    reward_to_risk: float
    live_price: float | None
    price_time: str | None
    checks: list[Check] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def build_ticket(*, ticker: str, entry: float, stop: float, target: float, equity: float,
                 risk_frac: float = 0.005, open_risk_rs: float = 0.0,
                 cash: float | None = None, live_price: float | None = None,
                 price_time: datetime | None = None, now: datetime | None = None,
                 tick: float = 0.05, max_chase_pct: float = 0.5,
                 max_price_age_s: int = 120, min_reward_to_risk: float = 3.0,
                 slippage_pct: float = 0.3, circuit_limits: tuple[float, float] | None = None,
                 vix: float | None = None, max_vix: float = 20.0) -> Ticket:
    now = now or datetime.now(IST)
    entry = _tick(entry, tick)
    stop_trigger = _tick(stop, tick)
    target = _tick(target, tick)
    stop_limit = _tick(stop_trigger * (1 - slippage_pct / 100), tick)   # SL-limit sells a bit lower
    per_share_risk = entry - stop_trigger
    checks: list[Check] = []

    def add(name, ok, detail):
        checks.append(Check(name, bool(ok), detail))

    add("stop below entry below target", stop_trigger < entry < target,
        f"{stop_trigger} < {entry} < {target}")
    if per_share_risk <= 0:
        raise ValueError("stop must be below entry")
    stop_pct = per_share_risk / entry * 100
    target_pct = (target / entry - 1) * 100
    rr = target_pct / stop_pct
    add("reward to risk", rr >= min_reward_to_risk, f"{rr:.2f} (minimum {min_reward_to_risk})")

    risk_budget = min(risk_frac * equity, 0.04 * equity - open_risk_rs)
    qty = max(0, math.floor(risk_budget / per_share_risk)) if risk_budget > 0 else 0
    qty = min(qty, math.floor(0.30 * equity / entry))
    if cash is not None:
        qty = min(qty, math.floor(cash / entry))
    add("position size at least 1 share", qty >= 1,
        f"{qty} shares (risk budget Rs {max(risk_budget, 0):,.0f})")
    value = qty * entry
    add("position within 30% of equity", value <= 0.30 * equity + 1e-6,
        f"Rs {value:,.0f} = {value / equity * 100:.1f}% of equity")
    add("total open risk within 4%", open_risk_rs + qty * per_share_risk <= 0.04 * equity + 1e-6,
        f"Rs {open_risk_rs + qty * per_share_risk:,.0f} = "
        f"{(open_risk_rs + qty * per_share_risk) / equity * 100:.2f}% of equity")

    if vix is not None:
        add("market volatility", vix <= max_vix, f"India VIX {vix:.2f} (limit {max_vix})")

    status = "READY"
    if live_price is None:
        add("live price available", False, "no live price: confirm the price in the app first")
        status = "WAITING"
    else:
        age = (now - price_time).total_seconds() if price_time else None
        fresh = age is not None and age <= max_price_age_s
        add("price is fresh", fresh,
            f"{'unknown age' if age is None else f'{age:.0f}s old'} (limit {max_price_age_s}s)")
        if live_price <= stop_trigger:
            add("price above the stop", False, f"live {live_price} is at or below the stop {stop_trigger}")
        gap = (live_price / entry - 1) * 100
        band = entry * (1 + max_chase_pct / 100)
        if live_price > band:
            add("entry still reachable", False,
                f"live {live_price} is {gap:+.2f}% from the entry limit {entry}; "
                f"the order rests until price falls to {entry}. Do not raise the limit.")
            status = "WAITING"
        else:
            add("entry still reachable", True, f"live {live_price} is {gap:+.2f}% from the entry limit")
        if circuit_limits:
            lo, hi = circuit_limits
            add("away from circuit limits", lo < stop_trigger and entry < hi * 0.98,
                f"circuits {lo} to {hi}")

    hard_fail = [c for c in checks if not c.ok and c.name not in ("entry still reachable",
                                                                  "live price available")]
    if hard_fail:
        status = "DO NOT TRADE"

    steps = [
        f"1. Open the stock {ticker} in INDmoney. Check the price is within "
        f"{max_chase_pct}% of {entry}; if it is higher, do not buy.",
        f"2. BUY {qty} shares as a LIMIT order at {entry}. Delivery (CNC), not intraday.",
        f"3. When filled, place a SELL stop-loss: trigger {stop_trigger}, limit {stop_limit} "
        f"(or stop-loss market if you prefer a guaranteed exit over a guaranteed price).",
        f"4. Place a SELL limit at the target {target} (a GTT order if the app offers it).",
        "5. If the buy has not filled by the end of the next session, cancel it. "
        "Do not chase.",
        "6. The order types and names in the app may differ slightly: confirm each field "
        "on the order screen before you tap confirm.",
    ]
    return Ticket(ticker=ticker, status=status, qty=qty, entry_limit=entry,
                  stop_trigger=stop_trigger, stop_limit=stop_limit, target=target,
                  position_value=round(value, 2), pct_of_equity=round(value / equity * 100, 2),
                  risk_rs=round(qty * per_share_risk, 2),
                  reward_rs=round(qty * (target - entry), 2),
                  stop_pct=round(stop_pct, 2), target_pct=round(target_pct, 2),
                  reward_to_risk=round(rr, 2), live_price=live_price,
                  price_time=price_time.strftime("%H:%M:%S") if price_time else None,
                  checks=checks, steps=steps)


def render_text(t: Ticket) -> str:
    mark = {"READY": "READY", "WAITING": "WAITING", "DO NOT TRADE": "DO NOT TRADE"}[t.status]
    lines = [f"=== ORDER TICKET: {t.ticker}   [{mark}] ===",
             f"BUY   {t.qty} shares  LIMIT {t.entry_limit}   (value Rs {t.position_value:,.0f}, "
             f"{t.pct_of_equity}% of equity)",
             f"STOP  trigger {t.stop_trigger}  limit {t.stop_limit}   "
             f"(-{t.stop_pct}%, you risk Rs {t.risk_rs:,.0f})",
             f"SELL  target {t.target}   (+{t.target_pct}%, you gain Rs {t.reward_rs:,.0f})",
             f"Reward to risk {t.reward_to_risk}:1"]
    if t.live_price is not None:
        lines.append(f"Live price {t.live_price} at {t.price_time or 'unknown time'}")
    lines.append("Checks:")
    for c in t.checks:
        lines.append(f"  [{'x' if c.ok else '!'}] {c.name}: {c.detail}")
    lines.append("Steps:")
    lines += [f"  {s}" for s in t.steps]
    lines.append("This tool places no orders. Research output, not investment advice.")
    return "\n".join(lines)
