"""Weekly and monthly index structures: held for days or weeks, not closed the same afternoon.

The daily desk (desks.fno_step) opens and closes within one session. This one books at most one NIFTY structure per weekly expiry and one
Bank Nifty structure per monthly expiry, holds it toward expiry, and exits on a target, a stop, or the calendar (expiry day for the
weekly, five days before expiry for the monthly). Which structure depends on two things written into the trade's thesis: whether options
are priced richer or cheaper than the index has really been moving (implied against realised volatility), and which way today's forecast leans.

    options rich, forecast up or sideways-up   -> put credit spread          (sell the side the market is moving away from)
    options rich, forecast down                -> call credit spread
    options cheap, a clear direction           -> debit spread in that direction
    options cheap, no direction                -> long straddle (weekly only: a monthly one needs more margin than the account has)

Every structure is checked against the broker's margin calculator before it is booked. Nothing here places an order.
"""
from __future__ import annotations

from datetime import date, datetime

import desks as D
import thesis as T

HOLD = {
    "weekly": {"under": "NIFTY", "lo": 2, "hi": 8, "delta": 0.16, "width": 0.008, "credit": (0.70, 1.00), "debit": (0.60, 0.50), "label": "NIFTY"},
    "monthly": {"under": "BANKNIFTY", "lo": 14, "hi": 50, "delta": 0.20, "width": 0.010, "credit": (0.50, 1.00), "debit": (0.60, 0.40), "label": "BANKNIFTY"},
}


def pick_expiry(exps: list[str], today: date, lo: int, hi: int, monthly: bool) -> str | None:
    """The first expiry between lo and hi days away; for monthly, only the last expiry of each calendar month counts."""
    if monthly:
        last: dict = {}
        for e in exps:
            last[e[:7]] = max(last.get(e[:7], e), e)
        exps = sorted(last.values())
    for e in exps:
        if lo <= (date.fromisoformat(e) - today).days <= hi:
            return e
    return None


def _fill(rows: list[dict], strike: float, kind: str, side: str):
    """(price, instrument key) to sell at the bid or buy at the ask, or None when there is no fair two-sided market."""
    m = D._px(rows, strike, kind)
    bid, ask = D._sell(m), D._buy(m)
    if bid <= 0 or ask <= 0 or ask - bid > max(1.0, 0.12 * (ask + bid) / 2):
        return None
    return (bid if side == "S" else ask), D._key(rows, strike, kind)


def _delta(rows: list[dict], strike: float, kind: str):
    for r in rows:
        if r["strike_price"] == strike:
            return ((r.get("call_options" if kind == "CE" else "put_options") or {}).get("option_greeks") or {}).get("delta")
    return None


def choose(horizon: str, rows: list[dict], spot: float, score: float, iv: float | None, rv: float | None):
    """-> (strategy name, [(side, strike, kind)], params) or (None, reason)."""
    H = HOLD[horizon]
    ks = sorted({r["strike_price"] for r in rows})
    near = lambda x: min(ks, key=lambda k: abs(k - x))
    width = spot * H["width"]
    if iv is None or rv is None:
        return None, "waiting for today's forecast: the realised volatility it uses is not ready yet"
    rich = iv >= rv
    atm = near(spot)
    if rich:
        kind = "PE" if score >= 0 else "CE"
        cands = [(abs(abs(_delta(rows, k, kind) or 0) - H["delta"]), k) for k in ks if ((k < spot) if kind == "PE" else (k > spot)) and _delta(rows, k, kind) and _fill(rows, k, kind, "S")]
        if not cands:
            return None, "no option near the target delta has a fair two-sided market"
        short = min(cands)[1]
        far = [k for k in ks if (k < short if kind == "PE" else k > short) and abs(k - short) >= width * 0.9 and _fill(rows, k, kind, "B")]
        if not far:
            return None, "no protective option far enough out has a fair market"
        long_ = min(far, key=lambda k: abs(abs(k - short) - width))
        return f"{horizon}_credit_spread", [("S", short, kind), ("B", long_, kind)], {"target": H["credit"][0], "stop": H["credit"][1], "risk": "fixed", "regime": f"options are rich (implied {iv:.1f}% against {rv:.1f}% realised)"}
    if abs(score) >= 0.2:
        kind, o = ("CE", near(atm + width * 1.5)) if score > 0 else ("PE", near(atm - width * 1.5))
        if o == atm:
            return None, "strikes too close to build a spread"
        return f"{horizon}_debit_spread", [("B", atm, kind), ("S", o, kind)], {"target": H["debit"][0], "stop": H["debit"][1], "risk": "hrll", "regime": f"options are cheap (implied {iv:.1f}% against {rv:.1f}% realised) and the forecast has a direction"}
    if horizon == "weekly" and iv is not None:
        return f"{horizon}_long_straddle", [("B", atm, "CE"), ("B", atm, "PE")], {"target": 0.5, "stop": 0.35, "risk": "hrhl", "regime": f"options are cheap (implied {iv:.1f}% against {rv:.1f}% realised) and the forecast has no direction"}
    return None, "options are cheap and the forecast has no direction: no edge worth the margin"


def hold_step(book: dict, now: datetime, ctx: dict, paused: set) -> None:
    """ctx: {u: {UNDER: {spot, prev, exps}}, chain(under, expiry)->rows, lot(under, expiry)->int, margin, room, env, acct, vix, view: {UNDER: {score, rv}}}"""
    R, t, day = D.FNO_RULES, D.mins(now.strftime("%H:%M")), now.strftime("%Y-%m-%d")
    for tr in book["trades"]:
        if tr["desk"] != "FNO" or tr["status"] != "OPEN" or tr.get("horizon", "daily") == "daily":
            continue
        under, exp = tr["underlying"], date.fromisoformat(tr["expiry"])
        spot = (ctx["u"].get(under) or {}).get("spot")
        late = now.date() > exp or (now.date() == exp and t >= D.mins("15:20"))
        if late and spot:                                              # held to expiry: cash-settled at the index close
            unit = T.profit_at(tr["legs"], tr["entry"], spot)
            D.finish(tr, unit, "expiry: settled at the index close", now, unit * tr["lot"] * tr["qty"] - R["leg_cost"] * len(tr["legs"]))
            continue
        rows = ctx["chain"](under, tr["expiry"])
        u = D._unit_pnl(tr["legs"], rows) if rows else None
        if u is None:
            continue
        pnl = u * tr["lot"] * tr["qty"] - R["leg_cost"] * len(tr["legs"])
        tr["pnl_rs"], tr["last"] = round(pnl, 2), round(u, 2)
        tgt, stp = u >= tr["target_u"], u <= -tr["stop_u"]
        calendar = tr["horizon"] == "monthly" and (exp - now.date()).days <= 5 and t >= D.mins(R["close"])
        if tgt or stp or calendar:
            D.finish(tr, u, "target" if tgt else "stop" if stp else "time: monthly positions leave five days before expiry", now, pnl)
    if now.weekday() >= 5 or not (D.mins(R["first"]) <= t <= D.mins(R["last"])):
        return
    M = ctx.get("margin")
    for horizon, H in HOLD.items():
        under, U_ = H["under"], ctx["u"].get(H["under"])
        if not U_ or not U_.get("spot") or any(x["status"] == "OPEN" and x["desk"] == "FNO" and x.get("horizon") == horizon for x in book["trades"]):
            continue
        exp = pick_expiry(U_["exps"], now.date(), H["lo"], H["hi"], horizon == "monthly")
        if not exp or book["seen"].get(f"{horizon}|{under}|{exp}"):
            continue
        rows, lot = ctx["chain"](under, exp), ctx["lot"](under, exp)
        if not rows or not lot:
            continue
        spot, vw = U_["spot"], (ctx.get("view") or {}).get(under) or {}
        iv, rv = D.atm_iv(rows, spot), vw.get("rv")
        got = choose(horizon, rows, spot, vw.get("score", 0.0), iv, rv)
        name, legs_def, p = (got[0], got[1], got[2]) if got[0] else (None, got[1], None)
        if not name:
            if M:
                M.skip("FNO", f"{horizon} {H['label']} structure", None, ctx["room"][0], legs_def, now)
            continue
        legs, fills = [], [(sd, k_, kd, _fill(rows, k_, kd, sd)) for sd, k_, kd in legs_def]
        if any(f[3] is None for f in fills):
            if M:
                M.skip("FNO", f"{horizon} {H['label']} {name.split('_', 1)[1].replace('_', ' ')}", None, ctx["room"][0], "a leg has no fair two-sided market right now (wide or missing bid and ask)", now)
            continue
        for side, strike, kind, f in fills:
            legs.append({"side": side, "strike": strike, "kind": kind, "entry": round(f[0], 2), "last": round(f[0], 2), "key": f[1]})
        net = sum(l["entry"] if l["side"] == "S" else -l["entry"] for l in legs)
        base, width = abs(net), (abs(legs[0]["strike"] - legs[1]["strike"]) if len(legs) == 2 and legs[0]["kind"] == legs[1]["kind"] else None)
        if base < 3 or (p["risk"] == "fixed" and (net <= 0 or net < 0.08 * (width or 1))):
            continue                                                 # a credit under 8% of the width pays too little for the risk
        days = max(1.0, float((date.fromisoformat(exp) - now.date()).days))
        legs_api = [(l["key"], lot, "BUY" if l["side"] == "B" else "SELL") for l in legs]
        margin, src = None, "Upstox margin calculator"
        if M:
            margin = M.final(legs_api)
        if margin is None or margin > ctx["room"][0]:
            if M:
                M.skip("FNO", f"{horizon} {H['label']} {name.split('_', 1)[1].replace('_', ' ')}", margin, ctx["room"][0], "needs more margin than the F&O limit has free" if margin else "margin could not be checked", now)
            continue
        ctx["room"][0] -= margin
        book["seen"][f"{horizon}|{under}|{exp}"] = day
        st = T.payoff_stats(legs, net, spot, iv or ctx.get("vix") or 15.0, days)
        env = {**(ctx.get("env") or {}), "rv": rv}
        exit_rule = (f"Take profit at {p['target']:.0%} of the {'credit' if net > 0 else 'debit'}, cut at {p['stop']:.0%} of it, otherwise hold: " +
                     ("it settles at the index close on expiry day." if horizon == "weekly" else "it leaves five days before expiry to avoid the final-week swings."))
        th = T.fno(name, horizon, legs, net, spot, U_.get("prev"), iv, ctx.get("vix"), days, lot, margin, ctx.get("acct") or 100000.0, exp, env, under=under, exit_rule=exit_rule, unit_target=base * p["target"], unit_stop=base * p["stop"])
        th["why"].insert(0, f"Regime: {p['regime']}.")
        D.mk(book, "FNO", name, f"{H['label']} {name.split('_', 1)[1].replace('_', ' ')} · {exp[5:]}", "SHORT" if net > 0 else "LONG", net, 1, now, expiry=exp, lot=lot, legs=legs, horizon=horizon, underlying=under,
             unit_base=base, target_u=round(base * p["target"], 2), stop_u=round(base * p["stop"], 2), risk_class=D.RISK[p["risk"]], max_gain_rs=round(st["max_gain"] * lot), max_loss_rs=round(st["max_loss"] * lot),
             margin_rs=margin, margin_src=src, thesis=th, reason=f"{H['label']} {spot:,.0f}; {p['regime']}; {horizon} structure held toward {exp}. {'Credit' if net > 0 else 'Debit'} {base:.1f} points.")
