"""Scalping agent: VWAP trend pullback on 1-minute bars, long and short, cash equities, intraday.

The idea: in a stock that is trending (price on the right side of VWAP, the 9-bar average on the right side of the 21-bar average and
sloping the same way), a shallow pullback to the 9-bar average that ends with a strong bar (a close beyond the previous bar, on above-average
volume) is a low-risk place to join the trend. The stop goes just beyond the pullback's extreme, the target is 1.5 times the distance to
the stop, and the trade is abandoned after 10 minutes. It trades only the most liquid names, never in the first 15 minutes or the last
hour, and skips any setup whose round-trip charges would eat more than a third of the target (flat Rs 10 an order makes small trades pointless).

Paper results include a 0.02% slippage assumption each way and the full charge estimate. Unproven: judge it by its closed-trade record, which the
gateway uses as the gate before any real order. Nothing here sends an order.
"""
from __future__ import annotations

from datetime import datetime

import desks as D
import gateway as G
import thesis as T

STRATEGY = "scalp_vwap_pullback"
R = {"first": "09:30", "last": "14:30", "stop_min": 0.15, "stop_max": 0.40, "rr": 1.5, "hold_min": 10, "max_open": 3, "max_day": 10, "cooldown": 20 * 60, "risk_pct": 0.25, "max_value": 40000.0,
     "turnover_cr": 100.0, "min_price": 100.0, "max_day_move": 4.0, "slip": 0.0002, "leverage": 5.0, "vol_x": 1.2, "ext_max": 0.8, "min_rc": 3.0, "universe": 25, "streak_stop": 3}


def ema(v: list[float], n: int) -> list[float]:
    k, e, out = 2 / (n + 1), None, []
    for x in v:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def universe(rows: list[dict]) -> list[str]:
    """The names worth scanning: the most liquid, not already near a circuit, priced high enough that a tick is small."""
    ok = [r for r in rows if r["price"] >= R["min_price"] and r["price"] * r["volume"] >= R["turnover_cr"] * 1e7 and abs(r["chg_pct"]) <= R["max_day_move"]]
    return [r["symbol"] for r in sorted(ok, key=lambda r: -r["price"] * r["volume"])[:R["universe"]]]


def signal(bars: list[list], tick: float = 0.05, P: dict | None = None) -> dict | None:
    """bars: completed 1-minute bars, oldest first, [HH:MM, o, h, l, c, v]. Returns the setup on the last bar, or None."""
    P = P or R
    n = len(bars)
    if n < 25:
        return None
    o, h, lo, c, v = ([b[k] for b in bars] for k in (1, 2, 3, 4, 5))
    vw, pv, vv = [], 0.0, 0.0
    for i in range(n):
        pv += (h[i] + lo[i] + c[i]) / 3 * v[i]
        vv += v[i]
        vw.append(pv / vv if vv else c[i])
    e9, e21, i = ema(c, 9), ema(c, 21), n - 1
    avg_v = sum(v[i - 20:i]) / 20
    if avg_v <= 0 or v[i] < P["vol_x"] * avg_v:
        return None
    ext = (c[i] / vw[i] - 1) * 100
    if c[i] > vw[i] and e9[i] > e21[i] and e21[i] > e21[i - 3] and c[i] > o[i] and c[i] > e9[i] and c[i] > h[i - 1] and min(lo[i - 3:i + 1]) <= e9[i] * 1.0003 and ext <= P["ext_max"]:
        return {"side": "LONG", "swing": min(lo[i - 3:i + 1]), "close": c[i], "vwap": vw[i], "ema9": e9[i], "ema21": e21[i], "vol_x": v[i] / avg_v, "ext": ext, "bar": bars[i][0]}
    if c[i] < vw[i] and e9[i] < e21[i] and e21[i] < e21[i - 3] and c[i] < o[i] and c[i] < e9[i] and c[i] < lo[i - 1] and max(h[i - 3:i + 1]) >= e9[i] * 0.9997 and -ext <= P["ext_max"]:
        return {"side": "SHORT", "swing": max(h[i - 3:i + 1]), "close": c[i], "vwap": vw[i], "ema9": e9[i], "ema21": e21[i], "vol_x": v[i] / avg_v, "ext": ext, "bar": bars[i][0]}
    return None


def levels(sig: dict, px: float, tick: float, sigma_pct: float | None = None, P: dict | None = None) -> tuple[float, float] | None:
    """Stop beyond the pullback's extreme and at least one standard deviation of the stock's own 10-minute noise away (the quant's floor),
    kept between 0.15% and 0.40% of price; target 1.5 times as far the other way."""
    P = P or R
    long_ = sig["side"] == "LONG"
    floor = max(P["stop_min"], sigma_pct or 0.0)
    if floor > P["stop_max"]:
        return None                                                  # too noisy right now for a stop this tight
    stop = G.rnd_dn(sig["swing"] - tick, tick) if long_ else G.rnd_up(sig["swing"] + tick, tick)
    d = abs(px - stop) / px * 100
    if d < floor:
        stop = G.rnd_dn(px * (1 - floor / 100), tick) if long_ else G.rnd_up(px * (1 + floor / 100), tick)
    elif d > P["stop_max"]:
        return None                                                  # the pullback was too deep: no tight stop exists
    dist = abs(px - stop)
    tgt = G.rnd_dn(px + P["rr"] * dist, tick) if long_ else G.rnd_up(px - P["rr"] * dist, tick)
    return stop, tgt


def _pnl(t: dict, px: float) -> float:
    d = 1 if t["side"] == "LONG" else -1
    ex = px * (1 - R["slip"] * d)
    return d * (ex - t["entry"]) * t["qty"] - G.round_trip_cost(t["entry"], ex, int(t["qty"]), "BUY" if d == 1 else "SELL")


def step(book: dict, now: datetime, ctx: dict) -> None:
    """ctx: rows {symbol: row}, bars {symbol: completed 1-minute bars}, room (spendable margin, list-like), acct (equity), tick(symbol) -> tick size, leverage(symbol) -> intraday multiple."""
    rows, hhmm, day = ctx["rows"], now.strftime("%H:%M"), now.strftime("%Y-%m-%d")
    name, P = ctx.get("name") or STRATEGY, {**R, **(ctx.get("params") or {})}          # the COO may have replaced the team with an improved one
    for t in book["trades"]:
        if t["desk"] != "EQUITY" or not str(t["strategy"]).startswith("scalp") or t["status"] != "OPEN":
            continue
        r = rows.get(t["symbol"])
        if not r:
            continue
        px = r["price"]
        t["last"], t["pnl_rs"] = px, round(_pnl(t, px), 2)
        long_ = t["side"] == "LONG"
        stop, tgt = (px <= t["stop"], px >= t["target_px"]) if long_ else (px >= t["stop"], px <= t["target_px"])
        late = hhmm >= "15:10" or (now.timestamp() - t["ts"]) >= R["hold_min"] * 60
        if stop or tgt or late:
            why = "stop" if stop else "target" if tgt else "time"
            d = 1 if long_ else -1
            ex = px * (1 - R["slip"] * d)
            D.finish(t, ex, why, now, _pnl(t, px))
            book.setdefault("cool", {})[t["symbol"]] = now.timestamp()
            book.setdefault("streak", {})
            book["streak"][day] = 0 if t["pnl_rs"] > 0 else book["streak"].get(day, 0) + 1
    if ctx.get("paused") or not (R["first"] <= hhmm <= R["last"]) or book.get("streak", {}).get(day, 0) >= R["streak_stop"]:
        return
    opened = [t for t in book["trades"] if t["desk"] == "EQUITY" and str(t["strategy"]).startswith("scalp")]
    if sum(t["status"] == "OPEN" for t in opened) >= R["max_open"] or sum(t["day"] == day for t in opened) >= R["max_day"]:
        return
    held = {t["symbol"] for t in opened if t["status"] == "OPEN"}
    for sym, bars in ctx["bars"].items():
        r = rows.get(sym)
        if not r or sym in held or now.timestamp() - book.get("cool", {}).get(sym, 0) < R["cooldown"] or len(bars) < 25:
            continue
        key = f"scalp|{sym}|{bars[-1][0]}"
        if book["seen"].get(key):
            continue
        book["seen"][key] = 1
        sig = signal(bars, ctx["tick"](sym), P)
        if not sig:
            continue
        tick = ctx["tick"](sym)
        long_ = sig["side"] == "LONG"
        px = r["price"] * (1 + R["slip"] if long_ else 1 - R["slip"])
        sigma = ctx["sigma"](sym) if ctx.get("sigma") else None
        lv = levels(sig, px, tick, sigma, P)
        if not lv:
            continue
        stop, tgt = lv
        dist = abs(px - stop)
        qty = min(int(ctx["acct"] * R["risk_pct"] / 100 // dist), int(R["max_value"] // px))
        if qty < 1:
            continue
        cost = G.round_trip_cost(px, tgt, qty, "BUY" if long_ else "SELL")
        gross = abs(tgt - px) * qty
        if gross < P["min_rc"] * cost:
            continue                                                  # charges would eat the target: not worth the order
        lev = max(1.0, min(float(ctx["leverage"](sym)), R["leverage"]))
        margin = round(qty * px / lev)
        if ctx.get("room") is not None and margin > ctx["room"][0]:
            continue
        if ctx.get("room") is not None:
            ctx["room"][0] -= margin
        side = "LONG" if long_ else "SHORT"
        reason = (f"{sig['side'].lower()} pullback to the 9-bar average on the 1-minute chart at {sig['bar']}: price {'above' if long_ else 'below'} VWAP ({sig['vwap']:,.2f}), "
                  f"averages stacked {'up' if long_ else 'down'}, a strong bar on {sig['vol_x']:.1f} times the usual volume. Stop {stop:,.2f}, target {tgt:,.2f}, out after {R['hold_min']} minutes"
                  + (f"; the quant set the stop at least one standard deviation of 10-minute noise ({sigma:.2f}%) away" if sigma else ""))
        t = D.mk(book, "EQUITY", name, f"{sym} {side.lower()}", side, px, qty, now, symbol=sym, stop=stop, target_px=tgt, hold_min=R["hold_min"], leverage=lev, margin_rs=margin, horizon="scalp",
                 risk_class="Scalp (1-minute bars)", reason=reason)
        t["id"] = f"K{now:%y%m%d}-{book['seq']}"                      # its own id series, so it never collides with the other equity book
        data = [f"{sym} at {px:,.2f}; 1-minute bars: close {sig['close']:,.2f}, VWAP {sig['vwap']:,.2f}, 9-bar average {sig['ema9']:,.2f}, 21-bar average {sig['ema21']:,.2f}, volume {sig['vol_x']:.1f} times the 20-bar average.",
                f"Size {qty} shares = Rs {qty * px:,.0f} of stock on about Rs {margin:,.0f} of margin ({lev:g} times intraday leverage assumed unless the broker's master says otherwise)."]
        th = T.directional("EQUITY", STRATEGY, "scalp", f"{sym} {side.lower()}", side, px, stop, tgt, dist * qty, abs(tgt - px) * qty, margin, ctx["acct"], data,
                           (ctx.get("news") or [])[:2] or ["Price action only: a scalp does not depend on news."], f"Out at the stop, the target, after {R['hold_min']} minutes, or by 15:10.",
                           "The gateway checks the same stop-loss, risk, charges and margin rules before any real order.")
        th["numbers"] += [["Round-trip charges", f"about Rs {cost:,.0f}", "Brokerage, STT, exchange fees, stamp duty and GST on one entry and one exit"], ["Target against charges", f"{gross / cost:.1f} times", f"The desk needs at least {R['min_rc']:g} times"]]
        t["thesis"] = th
        held.add(sym)
        if sum(x["status"] == "OPEN" for x in book["trades"] if str(x["strategy"]).startswith("scalp")) >= R["max_open"]:
            break
